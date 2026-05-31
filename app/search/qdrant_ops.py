"""
Qdrant client wrapper — all vector DB operations go through here.

Public interface:
    get_client() -> QdrantClient
    ensure_collection() -> None                              # idempotent; call at startup
    upsert(product_id, vector, payload)                      # single-point upsert
    search(query_vector, filters, top_k, sentiment_fields)   -> list[ProductResult]

Filters are standard Qdrant Filter objects — callers build them using
qdrant_client.models (FieldCondition, MatchValue, Range, etc.) and pass
them here.  This keeps qdrant_ops generic and the filter logic close to
the query-router / hybrid-search that understands user intent.

The client uses Qdrant Cloud in production (QDRANT_URL + QDRANT_API_KEY)
and local Docker in development (QDRANT_URL only).  No code change needed —
set the env vars.
"""

from __future__ import annotations

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


def ensure_catalogue_indexes(collection_name: str, keyword_fields: list[str]) -> None:
    """
    Create KEYWORD payload indexes for all hard-filter attrs in a catalogue.
    Called at startup for every CatalogueConfig so Qdrant filters don't 400.
    Idempotent — safe to call on every restart.
    """
    client = get_client()
    existing = {c.name for c in client.get_collections().collections}
    if collection_name not in existing:
        log.debug("Collection '%s' not found — skipping index creation", collection_name)
        return
    for field in keyword_fields:
        client.create_payload_index(
            collection_name=collection_name,
            field_name=field,
            field_schema=PayloadSchemaType.KEYWORD,
        )
    log.info("Keyword indexes ensured for '%s': %s", collection_name, keyword_fields)


# ── Write ─────────────────────────────────────────────────────────────────────

def upsert(product_id: str, vector: list[float], payload: dict) -> None:
    """Upsert a single product vector with its metadata payload."""
    get_client().upsert(
        collection_name=settings.qdrant_collection_name,
        points=[PointStruct(id=product_id, vector=vector, payload=payload)],
        wait=True,
    )


def upsert_batch(points: list[tuple[str, list[float], dict]]) -> None:
    """
    Upsert a batch of (product_id, vector, payload) tuples in one API call.
    More efficient than calling upsert() in a loop for large ingestion batches.
    """
    if not points:
        return
    get_client().upsert(
        collection_name=settings.qdrant_collection_name,
        points=[
            PointStruct(id=product_id, vector=vector, payload=payload)
            for product_id, vector, payload in points
        ],
        wait=True,
    )


# ── Read ──────────────────────────────────────────────────────────────────────

def search(
    query_vector: list[float],
    filters: Filter | None = None,
    top_k: int = 20,
    sentiment_fields: list[str] | None = None,
    collection_name: str | None = None,
) -> list[ProductResult]:
    """
    Vector similarity search.  Returns up to top_k results as ProductResult objects.

    Callers should request more candidates than they need (e.g. top_k=20) and
    pass results to reranker.rerank() to get the final top 10.
    """
    client = get_client()
    hits: list[ScoredPoint] = client.query_points(
        collection_name=collection_name or settings.qdrant_collection_name,
        query=query_vector,
        query_filter=filters,
        limit=top_k,
        with_payload=True,
    ).points

    return [_scored_point_to_result(hit, sentiment_fields or []) for hit in hits]


# ── Payload → ProductResult ───────────────────────────────────────────────────


def _scored_point_to_result(hit: ScoredPoint, sentiment_fields: list[str] | None = None) -> ProductResult:
    p = hit.payload or {}

    attributes: dict = {}
    if p.get("attributes_json"):
        try:
            attributes = json.loads(p["attributes_json"])
        except (json.JSONDecodeError, TypeError):
            attributes = {}

    sentiment_scores = {
        key: p[key]
        for key in (sentiment_fields or [])
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
        image_url=p.get("image_url"),
        description=p.get("description", ""),
        attributes=attributes,
        sentiment_scores=sentiment_scores,
        top_praise=p.get("top_praise"),
        top_complaint=p.get("top_complaint"),
        use_cases=p.get("use_cases") or [],
    )
