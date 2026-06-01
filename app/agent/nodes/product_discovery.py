"""
semantic_search — catalogue-aware SEMANTIC retrieval path.

Steps:
  1. Resolve CatalogueConfig from state.catalogue.
  2. Call extract_constraints() (config-driven, reads live Redis attr values)
     to get rewritten_query, hard Qdrant filters, and price bounds.
  3. Carry forward constraints from previous turn (_merge_constraints).
  4. Embed the rewritten query via app.search.embedder.embed().
  5. Build a Qdrant Filter from hard_filters + price bounds (USD).
  6. Search the catalogue's Qdrant collection with catalogue sentiment_fields.
  7. Rerank to top-10 via flashrank + run over-budget supplementary search concurrently.

Reads:  state.messages (last user message), state.catalogue, state.extracted_filters
Writes: state.search_results, state.sources, state.extracted_filters,
        state.budget_overrun_results

Outgoing edge: → personalise
"""

import asyncio
import logging

from qdrant_client.models import FieldCondition, Filter, MatchValue, Range

from app.agent.state import ShopSenseState
from app.search.catalogue_config import CatalogueConfig, get_catalogue
from app.search.constraint_extractor import ConstraintOutput, extract_constraints
from app.search.embedder import embed
from app.search.qdrant_ops import search
from app.search.reranker import rerank

log = logging.getLogger(__name__)

_USD_TO_INR = 83


def _merge_constraints(new: ConstraintOutput, prev: dict) -> ConstraintOutput:
    """Carry forward constraints from the previous turn for refinement queries.

    prev["hard_filters"] and prev price fields are used to fill nulls in new.
    Brand changed? Fresh search, carry nothing.
    """
    if not prev:
        return new

    prev_hard = prev.get("hard_filters") or {}
    updates: dict = {}
    query_prefix: list[str] = []

    # Brand change → fresh search context
    new_brand = (new.hard_filters or {}).get("brand")
    prev_brand = prev_hard.get("brand")
    if new_brand and prev_brand and new_brand.lower() != prev_brand.lower():
        return new

    # Carry forward null hard filters from previous turn
    if prev_hard:
        merged = {**new.hard_filters}
        for key, val in prev_hard.items():
            if val and not merged.get(key):
                merged[key] = val
                query_prefix.append(str(val))
        if merged != new.hard_filters:
            updates["hard_filters"] = merged

    # Carry forward price in USD (prev stored INR → convert back)
    if new.max_price is None and prev.get("max_price"):
        updates["max_price"] = prev["max_price"] / _USD_TO_INR
    if new.min_price is None and prev.get("min_price"):
        updates["min_price"] = prev["min_price"] / _USD_TO_INR

    if not updates:
        return new

    if query_prefix:
        updates["rewritten_query"] = f"{' '.join(query_prefix)} {new.rewritten_query}"
    return new.model_copy(update=updates)


def _build_qdrant_filter(constraints: ConstraintOutput) -> Filter | None:
    conditions: list[FieldCondition] = []

    for key, value in (constraints.hard_filters or {}).items():
        if value:
            conditions.append(FieldCondition(key=key, match=MatchValue(value=value)))

    if constraints.max_price is not None or constraints.min_price is not None:
        conditions.append(FieldCondition(
            key="current_price",
            range=Range(
                lte=constraints.max_price,
                gte=constraints.min_price,
            ),
        ))

    return Filter(must=conditions) if conditions else None


def _to_extracted_filters(constraints: ConstraintOutput) -> dict:
    """Normalise ConstraintOutput → extracted_filters shape expected by synthesise.

    Prices stored in INR so synthesise can display ₹ without conversion.
    use_case mapped from occasion/soft_attrs for domain-agnostic synthesis tips.
    """
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


async def semantic_search(state: ShopSenseState) -> dict:
    messages = state.get("messages", [])
    query = messages[-1]["content"] if messages else ""
    prev_filters = state.get("extracted_filters") or {}

    try:
        config: CatalogueConfig = get_catalogue(state.get("catalogue") or "fashion")
    except Exception:
        config = get_catalogue("fashion")

    # Step 1 — Catalogue-aware constraint extraction (reads live Redis attr values)
    try:
        constraints = await extract_constraints(query, config)
        constraints = _merge_constraints(constraints, prev_filters)
    except Exception as exc:
        log.warning("Constraint extraction failed (%s) — searching with raw query", exc)
        from app.search.constraint_extractor import _build_fallback
        constraints = _build_fallback(config, query)

    # Wardrobe context: if the user is shopping for a specific occasion this session
    # and the rewritten_query doesn't already mention it, enrich the embedding query
    # so Qdrant surfaces complementary pieces for that context.
    occasion_ctx = state.get("occasion_context") or ""
    if occasion_ctx and occasion_ctx.lower() not in constraints.rewritten_query.lower():
        constraints = constraints.model_copy(update={
            "rewritten_query": f"{constraints.rewritten_query} {occasion_ctx}"
        })

    # Step 2 — Embed rewritten query
    vector: list[float] = await asyncio.to_thread(embed, constraints.rewritten_query)

    # Step 3 — Build Qdrant filter (hard filters + price in USD)
    qdrant_filter = _build_qdrant_filter(constraints)

    # Step 4 — Search catalogue's collection with its sentiment fields
    candidates = await asyncio.to_thread(
        search, vector, qdrant_filter, 20,
        config.sentiment_fields, config.qdrant_collection,
    )

    # Step 5 — Rerank + over-budget search concurrently
    overrun_filter: Filter | None = None
    if constraints.max_price is not None:
        overrun_filter = Filter(must=[FieldCondition(
            key="current_price",
            range=Range(gt=constraints.max_price, lte=constraints.max_price * 1.30),
        )])

    reranked, overrun_candidates = await asyncio.gather(
        asyncio.to_thread(rerank, constraints.rewritten_query, candidates, 10),
        asyncio.to_thread(
            search, vector, overrun_filter, 5,
            config.sentiment_fields, config.qdrant_collection,
        ) if overrun_filter else asyncio.sleep(0),
    )
    budget_overrun = overrun_candidates if isinstance(overrun_candidates, list) else []

    return {
        "search_results": [r.model_dump() for r in reranked],
        "sources": [r.product_id for r in reranked],
        "extracted_filters": _to_extracted_filters(constraints),
        "budget_overrun_results": [r.model_dump() for r in budget_overrun],
    }
