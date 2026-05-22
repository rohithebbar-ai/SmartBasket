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


def _merge_filters(new: FilterExtractionOutput, prev: dict) -> FilterExtractionOutput:
    """Carry forward constraints from the previous turn when the current message is a refinement.

    Rule: if the user explicitly changed brand, treat as a fresh search (don't carry anything).
    Otherwise, fill in null fields from prev and prepend brand/category to rewritten_query
    so the embedding also benefits from the carried context.
    """
    if not prev:
        return new
    # Brand changed explicitly → fresh search, carry nothing
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

    # Enrich rewritten_query with carried-forward brand/category so the embedding
    # reflects the full search intent, not just the refinement phrase.
    if query_prefix:
        updates["rewritten_query"] = f"{' '.join(query_prefix)} {new.rewritten_query}"

    return new.model_copy(update=updates)


async def semantic_search(state: ShopSenseState) -> dict:
    messages = state.get("messages", [])
    query = messages[-1]["content"] if messages else ""
    prev_filters = state.get("extracted_filters") or {}

    # Step 1 — Filter extraction from current message only; carry-forward via _merge_filters
    try:
        raw = await call_llm(
            FILTER_EXTRACTION_PROMPT.format(query=query),
            tier="fast",
            max_tokens=300,
            temperature=0.0,
        )
        filters = FilterExtractionOutput.model_validate_json(raw)
        filters = _merge_filters(filters, prev_filters)
    except Exception as exc:
        log.warning("Filter extraction failed (%s) — using raw query with no filters", exc)
        filters = FilterExtractionOutput(rewritten_query=query)

    # Step 2 — Embed (sync function, run in thread to avoid blocking event loop)
    vector: list[float] = await asyncio.to_thread(embed, filters.rewritten_query)

    # Step 3 — Build Qdrant filter from non-null filter fields
    # IMPORTANT: The LLM extracts prices in INR; Qdrant stores prices in USD.
    # Divide by 83 to convert INR → USD before applying the Qdrant range filter.
    _INR_TO_USD = 1 / 83
    conditions: list[FieldCondition] = []
    if filters.brand:
        conditions.append(
            FieldCondition(key="brand", match=MatchValue(value=filters.brand))
        )
    if filters.category:
        conditions.append(
            FieldCondition(key="category", match=MatchValue(value=filters.category))
        )
    max_usd = filters.max_price * _INR_TO_USD if filters.max_price is not None else None
    min_usd = filters.min_price * _INR_TO_USD if filters.min_price is not None else None
    if max_usd is not None or min_usd is not None:
        conditions.append(
            FieldCondition(
                key="current_price",
                range=Range(lte=max_usd, gte=min_usd),
            )
        )

    qdrant_filter = Filter(must=conditions) if conditions else None

    # Step 4 — Qdrant search (sync)
    candidates = await asyncio.to_thread(search, vector, qdrant_filter, 20)

    # Step 5 — Rerank + over-budget search run concurrently (reranker takes ~200ms)
    overrun_filter: Filter | None = None
    if max_usd is not None:
        overrun_filter = Filter(must=[
            FieldCondition(
                key="current_price",
                range=Range(gt=max_usd, lte=max_usd * 1.30),
            )
        ])

    reranked, overrun_candidates = await asyncio.gather(
        asyncio.to_thread(rerank, filters.rewritten_query, candidates, 10),
        asyncio.to_thread(search, vector, overrun_filter, 5) if overrun_filter else asyncio.sleep(0),
    )
    results = reranked
    budget_overrun = overrun_candidates if isinstance(overrun_candidates, list) else []

    return {
        "search_results": [r.model_dump() for r in results],
        "sources": [r.product_id for r in results],
        "extracted_filters": filters.model_dump(),
        "budget_overrun_results": [r.model_dump() for r in budget_overrun],
    }
