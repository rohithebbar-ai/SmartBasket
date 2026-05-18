"""
Embedding client — provider-agnostic wrapper around Jina and NVIDIA APIs.

Public interface:
    embed(text: str) -> list[float]          # cached, query task mode
    embed_batch(texts: list[str]) -> list[list[float]]  # uncached, passage task mode

Both return vectors of length settings.embedding_dimensions (1024).
Switch provider by setting EMBEDDING_PROVIDER=JINA|NVIDIA in .env — no code change needed.

Caching: embed() is decorated with lru_cache(maxsize=2048).  Repeated queries
(e.g. the same search phrase within a session) return the cached vector without
hitting the API.  embed_batch() is intentionally uncached — ingestion batches
are large and unique.

Connection pooling: a single requests.Session is created at first call and reused
for the lifetime of the process.  This avoids a TLS handshake on every request,
which matters during bulk ingestion.
"""

from functools import lru_cache

import requests

from app.config import EmbeddingProvider, settings

# ── Session singleton ─────────────────────────────────────────────────────────

_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"Content-Type": "application/json"})
        _session.headers.update(_auth_header())
    return _session


def _auth_header() -> dict[str, str]:
    if settings.embedding_provider == EmbeddingProvider.JINA:
        if not settings.jina_api_key:
            raise RuntimeError("JINA_API_KEY is not set")
        return {"Authorization": f"Bearer {settings.jina_api_key}"}
    else:
        if not settings.nvidia_api_key:
            raise RuntimeError("NVIDIA_API_KEY is not set")
        return {"Authorization": f"Bearer {settings.nvidia_api_key}"}


# ── Provider implementations ──────────────────────────────────────────────────

def _jina_embed(texts: list[str], task: str) -> list[list[float]]:
    resp = _get_session().post(
        "https://api.jina.ai/v1/embeddings",
        json={
            "model": settings.jina_model,
            "task": task,
            "dimensions": settings.embedding_dimensions,
            "input": texts,
            "normalized": True,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return [item["embedding"] for item in resp.json()["data"]]


def _nvidia_embed(texts: list[str], input_type: str) -> list[list[float]]:
    resp = _get_session().post(
        "https://integrate.api.nvidia.com/v1/embeddings",
        json={
            "model": settings.nvidia_model,
            "input": texts,
            "input_type": input_type,   # "query" | "passage"
            "encoding_format": "float",
            "truncate": "END",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return [item["embedding"] for item in resp.json()["data"]]


# ── Public API ────────────────────────────────────────────────────────────────

@lru_cache(maxsize=2048)
def embed(text: str) -> list[float]:
    """
    Embed a single text in query mode.  Result is cached by text content.
    Use this everywhere in the application — search, agent, query router.
    """
    if settings.embedding_provider == EmbeddingProvider.JINA:
        return _jina_embed([text], task="retrieval.query")[0]
    else:
        return _nvidia_embed([text], input_type="query")[0]


def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts in passage mode (for indexing/ingestion).
    Not cached — call only from ingestion scripts, not at query time.
    """
    if not texts:
        return []
    if settings.embedding_provider == EmbeddingProvider.JINA:
        return _jina_embed(texts, task="retrieval.passage")
    else:
        return _nvidia_embed(texts, input_type="passage")


def cache_info() -> str:
    """Return lru_cache statistics as a human-readable string."""
    info = embed.cache_info()
    return f"hits={info.hits} misses={info.misses} size={info.currsize}/{info.maxsize}"


def clear_cache() -> None:
    """Clear the embedding cache — useful in tests."""
    embed.cache_clear()
