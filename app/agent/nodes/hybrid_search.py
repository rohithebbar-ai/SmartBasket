"""
hybrid_search — HYBRID retrieval path (RRF).

Delegates entirely to app.search.hybrid_search.hybrid_search(), which runs
SQL ranking and vector ranking concurrently and merges them with Reciprocal
Rank Fusion:  rrf_score = 1/(60 + sql_rank) + 1/(60 + vector_rank).

Reads:  state.messages (last user message)
Writes: state.search_results (list[dict] — RRF-merged, sorted by rrf_score desc)
        state.sources (list[str] — product_id strings)

Outgoing edge: → personalise
"""

import logging

from app.agent.state import ShopSenseState
from app.database import AsyncSessionLocal
from app.search.hybrid_search import hybrid_search as _hybrid_search

log = logging.getLogger(__name__)


async def hybrid_search(state: ShopSenseState) -> dict:
    messages = state.get("messages", [])
    query = messages[-1]["content"] if messages else ""

    async with AsyncSessionLocal() as db:
        results = await _hybrid_search(query=query, db=db, top_k=10)

    return {
        "search_results": [r.model_dump() for r in results],
        "sources": [r.product_id for r in results],
    }
