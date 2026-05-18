"""
Search router — pure semantic path (no LLM query routing).

POST /api/search/
    Embeds the query → searches Qdrant (top 20) → reranks with flashrank → returns top 10.

All three underlying operations (embed, Qdrant search, flashrank rerank) use
synchronous libraries.  Each is dispatched to the default thread-pool executor
via asyncio.to_thread so the FastAPI event loop is never blocked.

Filters in the request body are optional.  When provided they are translated to
Qdrant Filter objects and applied as pre-filters before vector search, which is
more accurate than post-filtering on large collections.
"""

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel, Field
from qdrant_client.models import FieldCondition, Filter, MatchValue, Range

from app.schemas.search import SearchResponse
from app.search.embedder import embed
from app.search.qdrant_ops import search
from app.search.reranker import rerank

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

@router.post("/", response_model=SearchResponse, summary="Semantic product search")
async def semantic_search(body: SearchRequest) -> SearchResponse:
    """
    Pure semantic search path — no LLM involved.

    1. Embed query via Jina/NVIDIA (cached by embedder.embed)
    2. Pre-filter + vector search in Qdrant (top 20 candidates)
    3. Rerank with flashrank cross-encoder (top_k results)
    4. Return SearchResponse with scores
    """
    # All three calls are sync I/O or CPU — run in thread pool
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
