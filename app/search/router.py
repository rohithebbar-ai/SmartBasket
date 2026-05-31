"""
Search router — catalogue-aware, query-routed search endpoint.

POST /api/search/
    1. Resolve catalogue config from body.catalogue (raises 400 on unknown).
    2. Extract constraints from the query (rewritten query, hard filters, prices).
    3. Classify query as SEMANTIC | ANALYTICAL | HYBRID (Bedrock Haiku, Redis-cached per catalogue).
    4. SEMANTIC   → embed rewritten_query → Qdrant top-20 → flashrank rerank → SearchResponse
    5. ANALYTICAL → run_nl_to_sql (with catalogue schema_hint) → AnalyticsResponse
    6. HYBRID     → RRF hybrid: SQL constrains candidates, Qdrant ranks within the filtered set.

Callers inspect `query_type` in the response to know which shape was returned.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from qdrant_client.models import FieldCondition, Filter, MatchValue, Range
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.search import AnalyticsResponse, SearchResponse
from app.search.catalogue_config import CatalogueConfig, get_catalogue
from app.search.constraint_extractor import ConstraintOutput, extract_constraints
from app.search.embedder import embed
from app.search.hybrid_search import hybrid_search
from app.search.nl_to_sql import run_nl_to_sql
from app.search.qdrant_ops import search
from app.search.query_router import classify_query
from app.search.reranker import rerank

log = logging.getLogger(__name__)
router = APIRouter()

SEARCH_ANALYTICAL_SCOPE = ["products", "reviews", "price_history"]


# ── Request / filter schema ───────────────────────────────────────────────────

class SearchFilters(BaseModel):
    brand: str | None = None
    category: str | None = None
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    in_stock_only: bool = False


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    catalogue: str = Field(default="fashion", description="Catalogue ID. Valid: fashion, electronics")
    filters: SearchFilters = Field(default_factory=SearchFilters)
    top_k: int = Field(default=10, ge=1, le=50)


# ── Filter builder ────────────────────────────────────────────────────────────

def _build_qdrant_filter(
    f: SearchFilters,
    hard_filters: dict[str, str | None],
    constraints: ConstraintOutput,
) -> Filter | None:
    conditions: list[FieldCondition] = []

    for key, value in hard_filters.items():
        if value:
            conditions.append(FieldCondition(key=key, match=MatchValue(value=value)))

    if f.brand:
        conditions.append(FieldCondition(key="brand", match=MatchValue(value=f.brand)))
    if f.category:
        conditions.append(FieldCondition(key="category", match=MatchValue(value=f.category)))

    if f.min_price is not None or f.max_price is not None:
        conditions.append(FieldCondition(
            key="current_price",
            range=Range(
                gte=f.min_price if f.min_price is not None else None,
                lte=f.max_price if f.max_price is not None else None,
            ),
        ))
    else:
        if constraints.max_price is not None:
            conditions.append(FieldCondition(
                key="current_price",
                range=Range(lte=constraints.max_price),
            ))
        if constraints.min_price is not None:
            conditions.append(FieldCondition(
                key="current_price",
                range=Range(gte=constraints.min_price),
            ))

    if f.in_stock_only:
        conditions.append(FieldCondition(key="stock_available", match=MatchValue(value=True)))

    return Filter(must=conditions) if conditions else None


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/", summary="Product search")
async def product_search(
    body: SearchRequest,
    db: AsyncSession = Depends(get_db),
) -> SearchResponse | AnalyticsResponse:
    """
    1. Resolve catalogue and extract constraints (rewritten query, hard filters, prices).
    2. Classify query type (SEMANTIC | ANALYTICAL | HYBRID) via Bedrock Haiku.
    3. SEMANTIC:   embed rewritten_query → Qdrant → rerank → SearchResponse
    4. ANALYTICAL: NL-to-SQL with catalogue schema_hint → AnalyticsResponse
    5. HYBRID:     RRF hybrid search
    """
    config: CatalogueConfig = get_catalogue(body.catalogue)

    constraints = await extract_constraints(body.query, config)
    routing = await classify_query(body.query, config=config)
    log.info("Search routing: catalogue=%s query_type=%s query='%.80s'", config.client_id, routing.type, body.query)

    # ── ANALYTICAL ────────────────────────────────────────────────────────────
    if routing.type == "ANALYTICAL":
        result = await run_nl_to_sql(
            query=body.query,
            schema_scope=SEARCH_ANALYTICAL_SCOPE,
            db=db,
            source="customer",
            use_few_shot=True,
            schema_hint=config.schema_hint,
        )
        if not result.validation_passed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "query_type": "ANALYTICAL",
                    "message": "Could not generate valid SQL for this query. Try rephrasing.",
                    "reasoning": routing.reasoning,
                },
            )
        return AnalyticsResponse(
            question=body.query,
            sql=result.generated_sql,
            results=result.rows,
            insight="",
            rows_returned=result.rows_returned,
        )

    # ── HYBRID ────────────────────────────────────────────────────────────────
    if routing.type == "HYBRID":
        results = await hybrid_search(
            query=constraints.rewritten_query,
            db=db,
            top_k=body.top_k,
            collection_name=config.qdrant_collection,
            sentiment_fields=config.sentiment_fields,
        )
        return SearchResponse(
            query=body.query,
            query_type="HYBRID",
            results=results,
            total=len(results),
        )

    # ── SEMANTIC ──────────────────────────────────────────────────────────────
    vector = await asyncio.to_thread(embed, constraints.rewritten_query)
    qdrant_filter = _build_qdrant_filter(body.filters, constraints.hard_filters, constraints)
    candidates = await asyncio.to_thread(
        search, vector, qdrant_filter, 20, config.sentiment_fields, config.qdrant_collection
    )

    if not candidates:
        return SearchResponse(query=body.query, query_type="SEMANTIC", results=[], total=0)

    results = await asyncio.to_thread(rerank, body.query, candidates, body.top_k)

    return SearchResponse(
        query=body.query,
        query_type="SEMANTIC",
        results=results,
        total=len(results),
    )
