"""
compare_products — COMPARE intent path.

Steps:
  1. Use Bedrock Haiku to extract 2-3 product names from the user message.
  2. For each name, embed and search Qdrant (top-1) to find the closest match.
  3. Enrich each Qdrant match with a PostgreSQL fetch:
       - Fresh current_price and stock_count (pricing engine updates these)
       - Aggregated sentiment averages from all reviews for that product
     Falls back to the Qdrant result as-is if the DB fetch fails.
  4. Sets state.query_type = "COMPARE" so synthesise formats a side-by-side comparison.
  5. Falls back to a broad semantic search on the full query if product
     extraction fails or returns nothing.

DB query uses AVG() over reviews joined per product — not LIMIT 1, which
would grab one random review's scores rather than the aggregated average.
Only the 5 sentiment columns that exist in the reviews table are fetched:
  battery, display, build_quality, value, performance.

Reads:  state.messages (last user message)
Writes: state.search_results (list[dict] — up to 3 enriched ProductResult dicts)
        state.sources (list[str] — product_id strings)
        state.query_type ("COMPARE")

Outgoing edge: → synthesise (bypasses personalise — deterministic fetch)
"""

import asyncio
import json
import logging

from sqlalchemy import text

from app.agent.prompts import COMPARE_EXTRACTION_PROMPT
from app.agent.state import ShopSenseState
from app.database import AsyncSessionLocal
from app.llm import call_llm
from app.schemas.search import ProductResult
from app.search.embedder import embed
from app.search.qdrant_ops import search

log = logging.getLogger(__name__)

# Fetches fresh price/stock from products and aggregated sentiment from reviews.
# Only columns that exist in the reviews table are selected.
_ENRICH_SQL = text("""
    SELECT
        p.id,
        p.name,
        p.brand,
        p.category,
        CAST(p.current_price AS FLOAT)       AS current_price,
        p.avg_rating,
        p.stock_count,
        p.specs,
        AVG(r.battery_sentiment)             AS battery_sentiment,
        AVG(r.display_sentiment)             AS display_sentiment,
        AVG(r.build_quality_sentiment)       AS build_quality_sentiment,
        AVG(r.value_sentiment)               AS value_sentiment,
        AVG(r.performance_sentiment)         AS performance_sentiment
    FROM products p
    LEFT JOIN reviews r ON r.product_id = p.id
    WHERE p.id = :product_id
    GROUP BY p.id, p.name, p.brand, p.category, p.current_price,
             p.avg_rating, p.stock_count, p.specs
""")


async def _find_product_in_qdrant(name: str) -> ProductResult | None:
    """Embed a product name and return the top-1 Qdrant result."""
    try:
        vector = await asyncio.to_thread(embed, name)
        results = await asyncio.to_thread(search, vector, None, 1)
        return results[0] if results else None
    except Exception as exc:
        log.warning("Qdrant lookup failed for %r: %s", name, exc)
        return None


async def _enrich_from_db(product_id: str, qdrant_result: ProductResult) -> ProductResult:
    """
    Fetch fresh price/stock and aggregated sentiment from PostgreSQL.
    Returns the enriched ProductResult, or the original Qdrant result on failure.
    """
    try:
        async with AsyncSessionLocal() as db:
            row = (await db.execute(_ENRICH_SQL, {"product_id": product_id})).mappings().first()

        if row is None:
            return qdrant_result

        sentiment_scores = {
            k: float(row[k])
            for k in (
                "battery_sentiment", "display_sentiment", "build_quality_sentiment",
                "value_sentiment", "performance_sentiment",
            )
            if row[k] is not None
        }

        specs: dict = {}
        if row["specs"]:
            if isinstance(row["specs"], str):
                try:
                    specs = json.loads(row["specs"])
                except json.JSONDecodeError:
                    specs = {}
            elif isinstance(row["specs"], dict):
                specs = row["specs"]

        return ProductResult(
            product_id=product_id,
            name=row["name"],
            brand=row["brand"],
            category=row["category"],
            current_price=float(row["current_price"]),
            avg_rating=float(row["avg_rating"]),
            relevance_score=qdrant_result.relevance_score,
            stock_available=int(row["stock_count"]) > 0,
            specs=specs,
            sentiment_scores=sentiment_scores,
            use_cases=qdrant_result.use_cases,  # Qdrant payload has use_cases; DB does not
        )
    except Exception as exc:
        log.warning("DB enrichment failed for product %s (%s) — using Qdrant result", product_id, exc)
        return qdrant_result


async def compare_products(state: ShopSenseState) -> dict:
    messages = state.get("messages", [])
    query = messages[-1]["content"] if messages else ""

    # Step 1 — Extract product names via LLM
    product_names: list[str] = []
    try:
        raw = await call_llm(
            COMPARE_EXTRACTION_PROMPT.format(message=query),
            tier="fast",
            max_tokens=100,
            temperature=0.0,
        )
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            product_names = [str(n) for n in parsed if isinstance(n, str)][:3]
    except Exception as exc:
        log.warning("Product name extraction failed (%s) — falling back to broad search", exc)

    # Step 2 — Find each product in Qdrant (parallel)
    found: list[ProductResult] = []
    if product_names:
        qdrant_results = await asyncio.gather(
            *[_find_product_in_qdrant(name) for name in product_names]
        )

        seen_ids: set[str] = set()
        candidates: list[ProductResult] = []
        for result in qdrant_results:
            if result and result.product_id not in seen_ids:
                candidates.append(result)
                seen_ids.add(result.product_id)

        # Step 3 — Enrich each Qdrant match from PostgreSQL (parallel)
        if candidates:
            found = list(await asyncio.gather(
                *[_enrich_from_db(r.product_id, r) for r in candidates]
            ))

    # Fallback — broad semantic search when extraction failed or found nothing
    if not found:
        log.warning("compare_products: no named products found — running broad search on full query")
        try:
            vector = await asyncio.to_thread(embed, query)
            candidates_fb = await asyncio.to_thread(search, vector, None, 3)
            if candidates_fb:
                found = list(await asyncio.gather(
                    *[_enrich_from_db(r.product_id, r) for r in candidates_fb[:3]]
                ))
        except Exception as exc:
            log.error("compare_products fallback search failed: %s", exc)

    return {
        "search_results": [r.model_dump() for r in found],
        "sources": [r.product_id for r in found],
        "query_type": "COMPARE",
    }
