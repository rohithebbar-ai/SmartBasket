"""
summarize_reviews — generates an aspect-aware review summary for a specific product.

Entry point: route_query routes here when query_type == "REVIEW_SUMMARY".

Product identification priority:
  1. state.sources[0] — product_id from the most recent search turn (most reliable)
  2. Simple name search against the products table using the user's message

Fetches up to 15 recent reviews from PostgreSQL, computes per-aspect averages from
the pre-populated sentiment columns, and generates a balanced summary via the
generation-tier LLM.

Returns an empty dict (graph falls through with no change) when no product can be
identified or no reviews exist — the caller's final_response is left unchanged so
the user sees a graceful empty state rather than an error.

Reads:  state.sources, state.messages
Writes: state.final_response (review summary)

Outgoing edge: → save_history
"""

import logging

from sqlalchemy import text

from app.agent.prompts import SUMMARIZE_REVIEWS_PROMPT
from app.agent.state import ShopSenseState
from app.database import AsyncSessionLocal
from app.llm import call_llm

log = logging.getLogger(__name__)

_REVIEWS_SQL = text("""
    SELECT
        r.rating,
        r.review_text,
        r.battery_sentiment,
        r.display_sentiment,
        r.build_quality_sentiment,
        r.value_sentiment,
        r.performance_sentiment,
        p.name,
        p.brand
    FROM reviews r
    JOIN products p ON p.id = r.product_id
    WHERE r.product_id = :product_id
    ORDER BY r.created_at DESC
    LIMIT 15
""")

_PRODUCT_NAME_SQL = text("""
    SELECT id, name, brand
    FROM products
    WHERE name ILIKE :pattern
    ORDER BY avg_rating DESC
    LIMIT 1
""")


def _avg_aspect(rows, key: str) -> float | None:
    vals = [r[key] for r in rows if r[key] is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


async def summarize_reviews(state: ShopSenseState) -> dict:
    product_id: str | None = None
    product_display = "this product"

    # ── Step 1: resolve product_id ────────────────────────────────────────────
    sources = state.get("sources") or []
    if sources:
        product_id = str(sources[0])

    if not product_id:
        # Fall back: extract a keyword from the latest message and search by name
        messages = state.get("messages") or []
        last_msg = messages[-1].get("content", "") if messages else ""
        if not last_msg:
            return {}

        # Use first 40 chars of the message as a rough product name hint
        name_hint = last_msg[:40].strip()
        try:
            async with AsyncSessionLocal() as db:
                row = (
                    await db.execute(_PRODUCT_NAME_SQL, {"pattern": f"%{name_hint}%"})
                ).mappings().first()
            if row:
                product_id = str(row["id"])
                product_display = f"{row['brand']} {row['name']}"
        except Exception as exc:
            log.warning("summarize_reviews product lookup failed: %s", exc)
            return {}

    if not product_id:
        return {}

    # ── Step 2: fetch reviews ────────────────────────────────────────────────
    try:
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(_REVIEWS_SQL, {"product_id": product_id})
            ).mappings().all()
    except Exception as exc:
        log.warning("summarize_reviews DB query failed for %s: %s", product_id, exc)
        return {}

    if not rows:
        return {
            "final_response": f"No customer reviews found for {product_display} yet."
        }

    if product_display == "this product":
        product_display = f"{rows[0]['brand']} {rows[0]['name']}"

    # ── Step 3: build summary context ────────────────────────────────────────
    avg_rating = round(sum(r["rating"] for r in rows) / len(rows), 1)

    aspects = {
        "Performance":      _avg_aspect(rows, "performance_sentiment"),
        "Battery":          _avg_aspect(rows, "battery_sentiment"),
        "Display":          _avg_aspect(rows, "display_sentiment"),
        "Build quality":    _avg_aspect(rows, "build_quality_sentiment"),
        "Value for money":  _avg_aspect(rows, "value_sentiment"),
    }
    aspect_line = ", ".join(
        f"{k}: {v}/5" for k, v in aspects.items() if v is not None
    )

    review_texts = [r["review_text"] for r in rows if r["review_text"]][:8]
    reviews_block = "\n".join(f'- "{t[:200]}"' for t in review_texts)

    prompt = SUMMARIZE_REVIEWS_PROMPT.format(
        product_name=product_display,
        review_count=len(rows),
        avg_rating=avg_rating,
        aspect_scores=aspect_line or "not available",
        reviews=reviews_block or "(no text reviews)",
    )

    # ── Step 4: generate summary ──────────────────────────────────────────────
    try:
        summary = await call_llm(prompt, tier="generation", max_tokens=250, temperature=0.3)
    except Exception as exc:
        log.warning("summarize_reviews LLM call failed: %s", exc)
        return {}

    return {"final_response": summary}
