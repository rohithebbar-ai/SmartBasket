"""
Search router — query-routed search endpoint.

POST /api/search/
    1. Classify query as SEMANTIC | ANALYTICAL | HYBRID (Bedrock Haiku, ~150ms, Redis-cached).
    2. SEMANTIC  → embed → Qdrant top-20 → flashrank rerank → return top_k.
    3. ANALYTICAL / HYBRID → 501 Not Implemented (NL-to-SQL engine lands on Day 10/11).

All three underlying search operations (embed, Qdrant, flashrank) use
synchronous libraries dispatched via asyncio.to_thread so the event loop is
never blocked.

Filters in the request body are optional pre-filters applied inside Qdrant
before vector search (more accurate than post-filtering on large collections).
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from qdrant_client.models import FieldCondition, Filter, MatchValue, Range

from app.schemas.search import SearchResponse
from app.search.embedder import embed
from app.search.qdrant_ops import search
from app.search.query_router import classify_query
from app.search.reranker import rerank

log = logging.getLogger(__name__)
router = APIRouter()


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

@router.post("/", response_model=SearchResponse, summary="Product search")
async def product_search(body: SearchRequest) -> SearchResponse:
    """
    1. Classify query type (SEMANTIC | ANALYTICAL | HYBRID) via Bedrock Haiku.
    2. SEMANTIC: embed → Qdrant → rerank → return results.
    3. ANALYTICAL / HYBRID: 501 until NL-to-SQL engine is available (Day 10/11).
    """
    routing = await classify_query(body.query)
    log.info("Search routing: query_type=%s query='%.80s'", routing.type, body.query)

    if routing.type != "SEMANTIC":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "query_type": routing.type,
                "reasoning": routing.reasoning,
                "message": (
                    f"{routing.type} queries require the NL-to-SQL engine "
                    "(available from Day 10). Try a descriptive product query instead."
                ),
            },
        )

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
