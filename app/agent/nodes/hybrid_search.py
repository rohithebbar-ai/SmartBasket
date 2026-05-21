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


async def hybrid_search(state: ShopSenseState) -> dict:
    messages = state.get("messages", [])
    query = messages[-1]["content"] if messages else ""

    # Run filter extraction and the full hybrid search concurrently
    async with AsyncSessionLocal() as db:
        filters, results = await asyncio.gather(
            _extract_filters(query),
            _hybrid_search(query=query, db=db, top_k=10),
        )

    # Supplementary over-budget Qdrant pass — runs after (fast, ~50ms)
    budget_overrun: list = []
    if filters.max_price is not None:
        overrun_filter = Filter(must=[
            FieldCondition(
                key="current_price",
                range=Range(gt=filters.max_price, lte=filters.max_price * 1.30),
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
