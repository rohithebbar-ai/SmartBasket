"""
semantic_search — SEMANTIC retrieval path.

Steps:
  1. Call Bedrock Haiku with FILTER_EXTRACTION_PROMPT to extract structured
     filters and a rewritten query. Parsed into FilterExtractionOutput.
  2. Embed the rewritten query via app.search.embedder.embed() (sync, lru_cache).
  3. Build a Qdrant Filter from non-null FilterExtractionOutput fields.
  4. Search Qdrant for top-20 candidates.
  5. Rerank to top-10 via flashrank cross-encoder.

Reads:  state.messages (last user message)
Writes: state.search_results (list[dict] — ProductResult.model_dump() per item)
        state.sources (list[str] — product_id strings)

Outgoing edge: → personalise
"""

import asyncio
import logging

from qdrant_client.models import FieldCondition, Filter, MatchValue, Range

from app.agent.prompts import FILTER_EXTRACTION_PROMPT
from app.agent.state import ShopSenseState
from app.llm import call_llm
from app.schemas.llm import FilterExtractionOutput
from app.search.embedder import embed
from app.search.qdrant_ops import search
from app.search.reranker import rerank

log = logging.getLogger(__name__)


async def semantic_search(state: ShopSenseState) -> dict:
    messages = state.get("messages", [])
    query = messages[-1]["content"] if messages else ""

    # Step 1 — Filter extraction
    try:
        raw = await call_llm(
            FILTER_EXTRACTION_PROMPT.format(query=query),
            tier="fast",
            max_tokens=300,
            temperature=0.0,
        )
        filters = FilterExtractionOutput.model_validate_json(raw)
    except Exception as exc:
        log.warning("Filter extraction failed (%s) — using raw query with no filters", exc)
        filters = FilterExtractionOutput(rewritten_query=query)

    # Step 2 — Embed (sync function, run in thread to avoid blocking event loop)
    vector: list[float] = await asyncio.to_thread(embed, filters.rewritten_query)

    # Step 3 — Build Qdrant filter from non-null filter fields
    conditions: list[FieldCondition] = []
    if filters.brand:
        conditions.append(
            FieldCondition(key="brand", match=MatchValue(value=filters.brand))
        )
    if filters.category:
        conditions.append(
            FieldCondition(key="category", match=MatchValue(value=filters.category))
        )
    if filters.max_price is not None or filters.min_price is not None:
        conditions.append(
            FieldCondition(
                key="current_price",
                range=Range(
                    lte=filters.max_price,
                    gte=filters.min_price,
                ),
            )
        )

    qdrant_filter = Filter(must=conditions) if conditions else None

    # Step 4 — Qdrant search (sync)
    candidates = await asyncio.to_thread(search, vector, qdrant_filter, 20)

    # Step 5 — Rerank top-20 → top-10 (sync cross-encoder, run in thread)
    results = await asyncio.to_thread(rerank, filters.rewritten_query, candidates, 10)

    return {
        "search_results": [r.model_dump() for r in results],
        "sources": [r.product_id for r in results],
    }
