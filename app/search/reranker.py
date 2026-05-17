"""
Flashrank cross-encoder reranker — implement in Week 2 (Day 8).

First-stage Qdrant search returns top 20 by cosine similarity.
The reranker scores each candidate against the original query using a
cross-encoder and returns the top_k by relevance — a meaningfully
different ranking from raw cosine similarity.

Runs locally on CPU (no API call, zero additional cost).

Public interface:
    rerank(query: str, candidates: list[ProductResult], top_k: int = 10)
        -> list[ProductResult]

Input and output are typed as ProductResult — never list[dict].
The relevance_score field on each result is updated with the reranker score.
"""

from app.schemas.search import ProductResult


def rerank(query: str, candidates: list[ProductResult], top_k: int = 10) -> list[ProductResult]:
    """
    Re-scores candidates against query using flashrank cross-encoder.
    Returns top_k results with updated relevance_score, sorted descending.
    """
    raise NotImplementedError("Implement in Week 2 — reranker (Day 8)")
