"""
Embedding client — implement in Week 2 (Day 8).

Wraps either Jina or NVIDIA embedding API based on settings.embedding_provider.
Uses requests.Session() for connection pooling: the session is created once at
startup and reused across all embed calls, so the TCP connection to the
embedding API is not re-established on every request (critical during ingestion
where thousands of products are embedded sequentially).

Public interface:
    embed_query(text: str) -> list[float]
    embed_batch(texts: list[str]) -> list[list[float]]

Both return vectors of length settings.embedding_dimensions (1024).
Switching providers requires only changing EMBEDDING_PROVIDER in .env —
no code change needed.
"""

import requests

from app.config import EmbeddingProvider, settings

# Module-level session — created once, reused for the lifetime of the process.
# requests.Session() pools the underlying TCP connection to the embedding API,
# avoiding per-request TLS handshake overhead during bulk ingestion.
_session: requests.Session | None = None


def get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(_build_auth_headers())
    return _session


def _build_auth_headers() -> dict[str, str]:
    if settings.embedding_provider == EmbeddingProvider.JINA:
        if not settings.jina_api_key:
            raise RuntimeError("JINA_API_KEY is not set")
        return {"Authorization": f"Bearer {settings.jina_api_key}"}
    else:
        if not settings.nvidia_api_key:
            raise RuntimeError("NVIDIA_API_KEY is not set")
        return {"Authorization": f"Bearer {settings.nvidia_api_key}"}


def embed_query(text: str) -> list[float]:
    """Embed a single query string. Returns a 1024-dim vector."""
    raise NotImplementedError("Implement in Week 2 — embedding provider selected (Day 8)")


def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Embed a batch of texts. Returns one 1024-dim vector per input.
    Uses the pooled session — safe to call in a tight ingestion loop.
    """
    raise NotImplementedError("Implement in Week 2 — embedding provider selected (Day 8)")
