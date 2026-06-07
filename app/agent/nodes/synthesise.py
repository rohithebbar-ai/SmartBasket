"""
synthesise — generates the final user-facing response via Bedrock Sonnet.

Adapts its context block by query_type:
  SEMANTIC / HYBRID / COMPARE → reads state.search_results (list[dict])
  ANALYTICAL                  → reads state.sql_results (list[dict]) + state.generated_sql

If nl_to_sql_search already wrote final_response (validation failure), this node
returns immediately without an LLM call so the error message reaches save_history.

Reads:  state.search_results | state.sql_results, state.query_type,
        state.messages, state.user_preferences, state.generated_sql
Writes: state.final_response (str)

Outgoing edge: → save_history
"""

import json
import logging

from app.agent.prompts import COMPARISON_SYNTHESIS_PROMPT, SYNTHESIS_PROMPT
from app.agent.state import ShopSenseState
from app.database import AsyncSessionLocal
from app.llm import call_llm
from app.redis_client import get_redis_client
from app.search.catalogue_config import get_catalogue
from sqlalchemy import text

log = logging.getLogger(__name__)

_FALLBACK_RESPONSE = (
    "I'm sorry, I couldn't find relevant results for your query. "
    "Please try rephrasing or use more specific terms."
)

_MAX_RESULTS_IN_PROMPT = 5
_MAX_SQL_ROWS_IN_PROMPT = 10


_USD_TO_INR = 83


def _format_product(r: dict, rank: int) -> str:
    price_inr = r.get("current_price", 0) * _USD_TO_INR
    lines = [
        f"{rank}. {r.get('brand', '')} {r.get('name', '')}",
        f"   Price: ₹{price_inr:,.0f}  |  Rating: {r.get('avg_rating', 0):.1f}/5",
    ]
    # specs for electronics; attributes for fashion — fall back gracefully
    display_data = r.get("specs") or r.get("attributes") or {}
    if display_data:
        spec_pairs = [f"{k}: {v}" for k, v in list(display_data.items())[:4]]
        lines.append("   Details: " + ", ".join(spec_pairs))
    sentiment = r.get("sentiment_scores") or {}
    if sentiment:
        top_sentiments = sorted(sentiment.items(), key=lambda x: x[1], reverse=True)[:3]
        lines.append("   Sentiment: " + ", ".join(f"{k}={v:.1f}" for k, v in top_sentiments))
    use_cases = r.get("use_cases") or []
    if use_cases:
        lines.append("   Use cases: " + ", ".join(use_cases[:3]))
    return "\n".join(lines)


def _build_comparison_table(products: list[dict]) -> str:
    """
    Build a structured attribute × product table for the COMPARISON_SYNTHESIS_PROMPT.
    Rows = attributes; columns = products. Only rows that differ across products
    are labelled "(same)" — still shown so the LLM has the full picture.
    """
    if not products:
        return "No products found."

    names = [f"{p.get('brand', '')} {p.get('name', '')}".strip() for p in products]
    header = "Attribute         | " + " | ".join(f"{n[:22]:<22}" for n in names)
    sep = "-" * len(header)
    rows = [header, sep]

    def row(label: str, vals: list[str]) -> str:
        return f"{label:<18}| " + " | ".join(f"{v[:22]:<22}" for v in vals)

    # Price
    rows.append(row("Price (₹)", [
        f"₹{p.get('current_price', 0) * _USD_TO_INR:,.0f}" for p in products
    ]))

    # Stock
    rows.append(row("In stock", [
        "Yes" if p.get("stock_available", True) else "⚠ Out of stock" for p in products
    ]))

    # Rating
    rows.append(row("Rating", [f"{p.get('avg_rating', 0):.1f}/5" for p in products]))

    # Fashion attributes from JSONB
    _ATTR_KEYS = [("colour", "Colour"), ("pattern", "Pattern"),
                  ("garment_group", "Garment group"), ("section", "Section")]
    for key, label in _ATTR_KEYS:
        vals = [str((p.get("attributes") or {}).get(key, "—")) for p in products]
        if any(v != "—" for v in vals):
            rows.append(row(label, vals))

    # Sentiment scores — only if present and differing meaningfully
    _SENT_LABELS = [
        ("style_sentiment", "Style"),
        ("quality_sentiment", "Quality"),
        ("fit_sentiment", "Fit"),
        ("comfort_sentiment", "Comfort"),
        ("versatility_sentiment", "Versatility"),
    ]
    for key, label in _SENT_LABELS:
        vals_raw = [(p.get("sentiment_scores") or {}).get(key) for p in products]
        if any(v is not None for v in vals_raw):
            vals = [f"{v:.1f}" if v is not None else "—" for v in vals_raw]
            rows.append(row(label, vals))

    return "\n".join(rows)


def _build_context_block(state: ShopSenseState, query_type: str) -> str:
    if query_type == "ANALYTICAL":
        rows = (state.get("sql_results") or [])[:_MAX_SQL_ROWS_IN_PROMPT]
        sql = state.get("generated_sql", "")
        if not rows:
            return "No data rows returned."
        return (
            f"SQL executed:\n{sql}\n\n"
            f"Results ({len(rows)} rows):\n"
            + json.dumps(rows, indent=2, default=str)
        )

    results = (state.get("search_results") or [])[:_MAX_RESULTS_IN_PROMPT]
    if not results:
        return "No products found."
    return "Products found:\n\n" + "\n\n".join(
        _format_product(r, i + 1) for i, r in enumerate(results)
    )


def _build_budget_overrun_section(state: ShopSenseState) -> str:
    overrun = (state.get("budget_overrun_results") or [])[:3]
    if not overrun:
        return ""
    lines = ["=== Slightly above budget (worth considering) ==="]
    filters = state.get("extracted_filters") or {}
    max_price = filters.get("max_price")
    for r in overrun:
        price = r.get("current_price", 0) * _USD_TO_INR
        premium = f"₹{price - max_price:,.0f} above budget" if max_price else ""
        specs = r.get("specs") or {}
        spec_note = ", ".join(f"{k}: {v}" for k, v in list(specs.items())[:2])
        lines.append(
            f"- {r.get('brand', '')} {r.get('name', '')}: ₹{price:,.0f}"
            + (f" ({premium})" if premium else "")
            + (f" | {spec_note}" if spec_note else "")
        )
    return "\n".join(lines)


async def _build_review_nudge(state: ShopSenseState) -> str:
    """
    Returns a one-line review prompt if the user has unreviewed delivered products
    and the current intent is informational (PRODUCT_SEARCH or COMPARE).
    Deletes the Redis pending_review key so the nudge only appears once.
    Returns "" on any failure or when the conditions are not met.
    """
    pending = state.get("pending_review_products") or []
    intent = state.get("intent", "")
    if not pending or intent not in ("PRODUCT_SEARCH", "COMPARE"):
        return ""

    user_id = state.get("user_id", "")
    product_names: list[str] = []
    try:
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    text("SELECT name FROM products WHERE id = ANY(:ids) LIMIT 3"),
                    {"ids": pending[:3]},
                )
            ).mappings().all()
            product_names = [row["name"] for row in rows]
    except Exception:
        pass

    if not product_names:
        product_names = ["your recent purchase"]

    names_str = " and ".join(product_names)
    nudge = f"By the way — how was {names_str}? You can leave a review anytime."

    # Delete the key so the nudge shows only once per delivery
    if user_id:
        try:
            redis = get_redis_client()
            await redis.delete(f"pending_review:{user_id}")
        except Exception:
            pass

    return nudge


async def synthesise(state: ShopSenseState) -> dict:
    # If validation failed in nl_to_sql_search, final_response is already set
    if state.get("final_response"):
        return {}

    messages = state.get("messages", [])
    question = messages[-1]["content"] if messages else ""
    query_type = state.get("query_type", "SEMANTIC").upper()
    user_preferences = state.get("user_preferences") or {}

    extracted = state.get("extracted_filters") or {}
    use_case = extracted.get("use_case") or "none"
    max_price = extracted.get("max_price")
    budget_context = f"₹{max_price:,.0f}" if max_price else "not specified"

    try:
        config = get_catalogue(state.get("catalogue") or "fashion")
        store_name = config.display_name
        domain_tips = config.synthesis_domain_tips
    except Exception:
        store_name = "ShopSense"
        domain_tips = ""

    # COMPARE gets its own structured prompt with a side-by-side attribute table
    if query_type == "COMPARE":
        products = (state.get("search_results") or [])[:3]
        comparison_table = _build_comparison_table(products)
        # occasion_context is written by compare_products from the user message;
        # fall back to use_case from extracted_filters, then to "everyday wear"
        compare_use_case = (
            state.get("occasion_context")
            or (use_case if use_case != "none" else "everyday wear")
        )
        prompt = COMPARISON_SYNTHESIS_PROMPT.format(
            store_name=store_name,
            question=question,
            use_case=compare_use_case,
            comparison_table=comparison_table,
        )
        max_tokens = 400
    else:
        context_block = _build_context_block(state, query_type)
        budget_overrun_section = _build_budget_overrun_section(state)
        prompt = SYNTHESIS_PROMPT.format(
            question=question,
            query_type=query_type,
            context_block=context_block,
            budget_overrun_section=budget_overrun_section,
            use_case=use_case,
            budget_context=budget_context,
            user_preferences=json.dumps(user_preferences) if user_preferences else "none",
            domain_tips=domain_tips,
            store_name=store_name,
        )
        max_tokens = 450

    review_nudge = await _build_review_nudge(state)

    try:
        response = await call_llm(prompt, tier="generation", max_tokens=max_tokens, temperature=0.3)
    except Exception as exc:
        log.error("Synthesis LLM call failed: %s", exc)
        response = _FALLBACK_RESPONSE

    if review_nudge:
        response = f"{review_nudge}\n\n{response}"

    sources = state.get("sources") or []
    return {
        "final_response": response,
        "sources": sources,
    }
