"""
hybrid_search — catalogue-aware HYBRID retrieval path (RRF).

Delegates to app.search.hybrid_search.hybrid_search() for SQL + vector merge.
Runs extract_constraints() in parallel with the hybrid search to capture filters
for the synthesise node, then runs a supplementary over-budget Qdrant pass.

Reads:  state.messages, state.catalogue, state.extracted_filters
Writes: state.search_results, state.sources, state.extracted_filters,
        state.budget_overrun_results

Outgoing edge: → personalise
"""

import asyncio
import logging

from qdrant_client.models import FieldCondition, Filter, Range

from app.agent.state import ShopSenseState
from app.database import AsyncSessionLocal
from app.search.catalogue_config import CatalogueConfig, get_catalogue
from app.search.constraint_extractor import ConstraintOutput, extract_constraints
from app.search.embedder import embed
from app.search.hybrid_search import hybrid_search as _hybrid_search
from app.search.qdrant_ops import search as qdrant_search

log = logging.getLogger(__name__)

_USD_TO_INR = 83


def _merge_constraints(new: ConstraintOutput, prev: dict) -> ConstraintOutput:
    """Carry forward non-null constraints from previous turn for refinement queries."""
    if not prev:
        return new

    prev_hard = prev.get("hard_filters") or {}
    updates: dict = {}
    query_prefix: list[str] = []

    new_brand = (new.hard_filters or {}).get("brand")
    prev_brand = prev_hard.get("brand")
    if new_brand and prev_brand and new_brand.lower() != prev_brand.lower():
        return new

    if prev_hard:
        merged = {**new.hard_filters}
        for key, val in prev_hard.items():
            if val and not merged.get(key):
                merged[key] = val
                query_prefix.append(str(val))
        if merged != new.hard_filters:
            updates["hard_filters"] = merged

    if new.max_price is None and prev.get("max_price"):
        updates["max_price"] = prev["max_price"] / _USD_TO_INR
    if new.min_price is None and prev.get("min_price"):
        updates["min_price"] = prev["min_price"] / _USD_TO_INR

    if not updates:
        return new

    if query_prefix:
        updates["rewritten_query"] = f"{' '.join(query_prefix)} {new.rewritten_query}"
    return new.model_copy(update=updates)


def _to_extracted_filters(constraints: ConstraintOutput) -> dict:
    max_inr = constraints.max_price * _USD_TO_INR if constraints.max_price is not None else None
    min_inr = constraints.min_price * _USD_TO_INR if constraints.min_price is not None else None
    use_case = constraints.occasion or (constraints.soft_attrs or {}).get("use_case")
    return {
        "rewritten_query": constraints.rewritten_query,
        "max_price": max_inr,
        "min_price": min_inr,
        "use_case": use_case,
        "hard_filters": constraints.hard_filters,
        "soft_attrs": constraints.soft_attrs,
        "detected_currency": constraints.detected_currency,
    }


async def hybrid_search(state: ShopSenseState) -> dict:
    messages = state.get("messages", [])
    query = messages[-1]["content"] if messages else ""
    prev_filters = state.get("extracted_filters") or {}

    try:
        config: CatalogueConfig = get_catalogue(state.get("catalogue") or "fashion")
    except Exception:
        config = get_catalogue("fashion")

    # Run constraint extraction and hybrid search concurrently
    async with AsyncSessionLocal() as db:
        constraints, results = await asyncio.gather(
            extract_constraints(query, config),
            _hybrid_search(
                query=query,
                db=db,
                top_k=10,
                collection_name=config.qdrant_collection,
                sentiment_fields=config.sentiment_fields,
            ),
        )
    constraints = _merge_constraints(constraints, prev_filters)

    # Over-budget supplementary Qdrant pass (prices in Qdrant are USD)
    budget_overrun: list = []
    if constraints.max_price is not None:
        max_usd = constraints.max_price
        overrun_filter = Filter(must=[FieldCondition(
            key="current_price",
            range=Range(gt=max_usd, lte=max_usd * 1.30),
        )])
        try:
            vector = await asyncio.to_thread(embed, constraints.rewritten_query)
            budget_overrun = await asyncio.to_thread(
                qdrant_search, vector, overrun_filter, 5,
                config.sentiment_fields, config.qdrant_collection,
            )
        except Exception as exc:
            log.warning("Hybrid over-budget search failed (non-fatal): %s", exc)

    return {
        "search_results": [r.model_dump() for r in results],
        "sources": [r.product_id for r in results],
        "extracted_filters": _to_extracted_filters(constraints),
        "budget_overrun_results": [r.model_dump() for r in budget_overrun],
    }
