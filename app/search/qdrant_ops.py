"""
Qdrant client wrapper — all vector DB operations go through here.

Public interface:
    get_client() -> QdrantClient
    ensure_collection() -> None          # idempotent; call at startup
    upsert(product_id, vector, payload)  # single-point upsert
    search(query_vector, filters, top_k) -> list[ProductResult]

Filters are standard Qdrant Filter objects — callers build them using
qdrant_client.models (FieldCondition, MatchValue, Range, etc.) and pass
them here.  This keeps qdrant_ops generic and the filter logic close to
the query-router / hybrid-search that understands user intent.

The client uses Qdrant Cloud in production (QDRANT_URL + QDRANT_API_KEY)
and local Docker in development (QDRANT_URL only).  No code change needed —
set the env vars.
"""

import json
import logging

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    Filter,
    PayloadSchemaType,
    PointStruct,
    ScoredPoint,
    VectorParams,
)

from app.config import settings
from app.schemas.search import ProductResult

log = logging.getLogger(__name__)

# ── Client singleton ──────────────────────────────────────────────────────────

_client: QdrantClient | None = None


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,  # None for local Docker
            timeout=30,
        )
    return _client


# ── Collection management ─────────────────────────────────────────────────────

def ensure_collection() -> None:
    """Create the products collection and payload indexes if they don't exist."""
    client = get_client()
    existing = {c.name for c in client.get_collections().collections}
    if settings.qdrant_collection_name not in existing:
        client.create_collection(
            collection_name=settings.qdrant_collection_name,
            vectors_config=VectorParams(
                size=settings.embedding_dimensions,
                distance=Distance.COSINE,
            ),
        )
        log.info(
            "Created Qdrant collection '%s' (%d-dim, cosine)",
            settings.qdrant_collection_name,
            settings.embedding_dimensions,
        )
    else:
        log.debug("Collection '%s' already exists", settings.qdrant_collection_name)

    _ensure_payload_indexes(client)


def _ensure_payload_indexes(client: QdrantClient) -> None:
    """
    Create payload indexes for all filterable fields.
    Qdrant requires an index on a field before it can be used in a Filter —
    without it, range/match queries return a 400 Bad Request.
    This call is idempotent: re-creating an existing index is a no-op.
    """
    col = settings.qdrant_collection_name
    indexes = {
        "current_price":   PayloadSchemaType.FLOAT,
        "brand":           PayloadSchemaType.KEYWORD,
        "category":        PayloadSchemaType.KEYWORD,
        "stock_available": PayloadSchemaType.BOOL,
    }
    for field, schema_type in indexes.items():
        client.create_payload_index(
            collection_name=col,
            field_name=field,
            field_schema=schema_type,
        )
    log.debug("Payload indexes ensured for collection '%s'", col)


# ── Write ─────────────────────────────────────────────────────────────────────

def upsert(product_id: str, vector: list[float], payload: dict) -> None:
    """Upsert a single product vector with its metadata payload."""
    get_client().upsert(
        collection_name=settings.qdrant_collection_name,
        points=[PointStruct(id=product_id, vector=vector, payload=payload)],
        wait=True,
    )


# ── Read ──────────────────────────────────────────────────────────────────────

def search(
    query_vector: list[float],
    filters: Filter | None = None,
    top_k: int = 20,
) -> list[ProductResult]:
    """
    Vector similarity search.  Returns up to top_k results as ProductResult objects.

    Callers should request more candidates than they need (e.g. top_k=20) and
    pass results to reranker.rerank() to get the final top 10.
    """
    client = get_client()
    hits: list[ScoredPoint] = client.query_points(
        collection_name=settings.qdrant_collection_name,
        query=query_vector,
        query_filter=filters,
        limit=top_k,
        with_payload=True,
    ).points

    return [_scored_point_to_result(hit) for hit in hits]


# ── Payload → ProductResult ───────────────────────────────────────────────────

_SENTIMENT_KEYS = (
    "battery_sentiment",
    "display_sentiment",
    "build_quality_sentiment",
    "value_sentiment",
    "performance_sentiment",
    "keyboard_sentiment",
    "thermal_sentiment",
)


def _scored_point_to_result(hit: ScoredPoint) -> ProductResult:
    p = hit.payload or {}

    specs: dict = {}
    if p.get("specs_json"):
        try:
            specs = json.loads(p["specs_json"])
        except (json.JSONDecodeError, TypeError):
            specs = {}

    sentiment_scores = {
        key: p[key]
        for key in _SENTIMENT_KEYS
        if p.get(key) is not None
    }

    return ProductResult(
        product_id=p.get("product_id", str(hit.id)),
        name=p.get("name", ""),
        brand=p.get("brand", ""),
        category=p.get("category", ""),
        current_price=float(p["current_price"]) if p.get("current_price") is not None else 0.0,
        avg_rating=float(p["avg_rating"]) if p.get("avg_rating") is not None else 0.0,
        relevance_score=float(hit.score),
        stock_available=bool(p.get("stock_available", True)),
        specs=specs,
        sentiment_scores=sentiment_scores,
        use_cases=p.get("use_cases") or [],
    )
