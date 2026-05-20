"""
Search router — query-routed search endpoint.

POST /api/search/
    1. Classify query as SEMANTIC | ANALYTICAL | HYBRID (Bedrock Haiku, ~150ms, Redis-cached).
    2. SEMANTIC   → embed → Qdrant top-20 → flashrank rerank → SearchResponse
    3. ANALYTICAL → run_nl_to_sql → AnalyticsResponse
    4. HYBRID     → 501 Not Implemented (RRF hybrid search lands on Day 11)

Callers inspect `query_type` in the response to know which shape was returned.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from qdrant_client.models import FieldCondition, Filter, MatchValue, Range
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.search import AnalyticsResponse, SearchResponse
from app.search.embedder import embed
from app.search.hybrid_search import hybrid_search
from app.search.nl_to_sql import run_nl_to_sql
from app.search.qdrant_ops import search
from app.search.query_router import classify_query
from app.search.reranker import rerank

log = logging.getLogger(__name__)
router = APIRouter()

# Tables available for customer-facing ANALYTICAL queries (no orders — user-scoped)
SEARCH_ANALYTICAL_SCOPE = ["products", "reviews", "price_history"]


# ── Request / filter schema ───────────────────────────────────────────────────

class SearchFilters(BaseModel):
    brand: str | None = None
    category: str | None = None
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    in_stock_only: bool = False


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Natural-language search query")
    filters: SearchFilters = Field(default_factory=SearchFilters)
    top_k: int = Field(default=10, ge=1, le=50, description="Number of results to return after reranking")


# ── Filter builder ────────────────────────────────────────────────────────────

def _build_qdrant_filter(f: SearchFilters) -> Filter | None:
    conditions: list[FieldCondition] = []

    if f.brand:
        conditions.append(FieldCondition(key="brand", match=MatchValue(value=f.brand)))

    if f.category:
        conditions.append(FieldCondition(key="category", match=MatchValue(value=f.category)))

    if f.min_price is not None or f.max_price is not None:
        conditions.append(FieldCondition(
            key="current_price",
            range=Range(gte=f.min_price, lte=f.max_price),
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
    1. Classify query type (SEMANTIC | ANALYTICAL | HYBRID) via Bedrock Haiku.
    2. SEMANTIC:   embed → Qdrant → rerank → SearchResponse
    3. ANALYTICAL: NL-to-SQL → AnalyticsResponse (no insight synthesis — raw results)
    4. HYBRID:     501 until Day 11 RRF hybrid search is built
    """
    routing = await classify_query(body.query)
    log.info("Search routing: query_type=%s query='%.80s'", routing.type, body.query)

    # ── ANALYTICAL ────────────────────────────────────────────────────────────
    if routing.type == "ANALYTICAL":
        result = await run_nl_to_sql(
            query=body.query,
            schema_scope=SEARCH_ANALYTICAL_SCOPE,
            db=db,
            source="customer",
            use_few_shot=True,
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
            insight="",   # no Sonnet synthesis on the search path — speed matters
            rows_returned=result.rows_returned,
        )

    # ── HYBRID ────────────────────────────────────────────────────────────────
    if routing.type == "HYBRID":
        results = await hybrid_search(query=body.query, db=db, top_k=body.top_k)
        return SearchResponse(
            query=body.query,
            query_type="HYBRID",
            results=results,
            total=len(results),
        )

    # ── SEMANTIC ──────────────────────────────────────────────────────────────
    vector = await asyncio.to_thread(embed, body.query)

    qdrant_filter = _build_qdrant_filter(body.filters)
    candidates = await asyncio.to_thread(search, vector, qdrant_filter, 20)

    if not candidates:
        return SearchResponse(query=body.query, query_type="SEMANTIC", results=[], total=0)

    results = await asyncio.to_thread(rerank, body.query, candidates, body.top_k)

    return SearchResponse(
        query=body.query,
        query_type="SEMANTIC",
        results=results,
        total=len(results),
    )
