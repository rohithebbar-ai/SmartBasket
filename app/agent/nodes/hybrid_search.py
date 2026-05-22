"""
hybrid_search — HYBRID retrieval path (RRF).

Delegates to app.search.hybrid_search.hybrid_search() for SQL + vector merge.
Also runs filter extraction in parallel to capture max_price and use_case for
the synthesise node, and performs a supplementary Qdrant pass for products just
above budget (up to 30% over max_price) so synthesise can offer the Rufus-style
"this is ₹X above your budget — worth considering?" proactive suggestion.

Reads:  state.messages (last user message)
Writes: state.search_results       (RRF-merged results, sorted by rrf_score)
        state.sources              (product_id strings)
        state.extracted_filters    (FilterExtractionOutput fields)
        state.budget_overrun_results (products just above max_price, if set)

Outgoing edge: → personalise
"""

import asyncio
import logging

from qdrant_client.models import FieldCondition, Filter, Range

from app.agent.prompts import FILTER_EXTRACTION_PROMPT
from app.agent.state import ShopSenseState
from app.database import AsyncSessionLocal
from app.llm import call_llm
from app.schemas.llm import FilterExtractionOutput
from app.search.embedder import embed
from app.search.hybrid_search import hybrid_search as _hybrid_search
from app.search.qdrant_ops import search as qdrant_search

log = logging.getLogger(__name__)


async def _extract_filters(query: str) -> FilterExtractionOutput:
    try:
        raw = await call_llm(
            FILTER_EXTRACTION_PROMPT.format(query=query),
            tier="fast", max_tokens=300, temperature=0.0,
        )
        return FilterExtractionOutput.model_validate_json(raw)
    except Exception as exc:
        log.warning("Hybrid filter extraction failed (%s) — no filter context", exc)
        return FilterExtractionOutput(rewritten_query=query)


def _merge_filters(new: FilterExtractionOutput, prev: dict) -> FilterExtractionOutput:
    """Carry forward constraints from the previous turn when the current message is a refinement."""
    if not prev:
        return new
    if new.brand and prev.get("brand") and new.brand.lower() != prev["brand"].lower():
        return new

    updates: dict = {}
    query_prefix: list[str] = []

    if not new.brand and prev.get("brand"):
        updates["brand"] = prev["brand"]
        query_prefix.append(prev["brand"])
    if new.max_price is None and prev.get("max_price"):
        updates["max_price"] = prev["max_price"]
    if new.min_price is None and prev.get("min_price"):
        updates["min_price"] = prev["min_price"]
    if not new.category and prev.get("category"):
        updates["category"] = prev["category"]
        query_prefix.append(prev["category"])

    if not updates:
        return new

    if query_prefix:
        updates["rewritten_query"] = f"{' '.join(query_prefix)} {new.rewritten_query}"

    return new.model_copy(update=updates)


async def hybrid_search(state: ShopSenseState) -> dict:
    messages = state.get("messages", [])
    query = messages[-1]["content"] if messages else ""
    prev_filters = state.get("extracted_filters") or {}

    # Run filter extraction and hybrid search concurrently
    async with AsyncSessionLocal() as db:
        filters, results = await asyncio.gather(
            _extract_filters(query),
            _hybrid_search(query=query, db=db, top_k=10),
        )
    filters = _merge_filters(filters, prev_filters)

    # Supplementary over-budget Qdrant pass — prices in Qdrant are USD; convert from INR
    _INR_TO_USD = 1 / 83
    budget_overrun: list = []
    if filters.max_price is not None:
        max_usd = filters.max_price * _INR_TO_USD
        overrun_filter = Filter(must=[
            FieldCondition(
                key="current_price",
                range=Range(gt=max_usd, lte=max_usd * 1.30),
            )
        ])
        try:
            vector = await asyncio.to_thread(embed, filters.rewritten_query)
            budget_overrun = await asyncio.to_thread(qdrant_search, vector, overrun_filter, 5)
        except Exception as exc:
            log.warning("Hybrid over-budget search failed (non-fatal): %s", exc)

    return {
        "search_results": [r.model_dump() for r in results],
        "sources": [r.product_id for r in results],
        "extracted_filters": filters.model_dump(),
        "budget_overrun_results": [r.model_dump() for r in budget_overrun],
    }
