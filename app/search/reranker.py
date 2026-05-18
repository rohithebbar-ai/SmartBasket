"""
Flashrank cross-encoder reranker.

First-stage Qdrant search returns top 20 by cosine similarity.
The reranker scores each candidate against the original query using a
cross-encoder (ms-marco-MiniLM-L-12-v2) and returns the top_k by relevance.
Cross-encoder ranking is meaningfully different from cosine similarity — it
reads query and passage together rather than comparing independent vectors.

Runs entirely on local CPU.  No API call, no extra cost.

Public interface:
    rerank(query, candidates, top_k=10) -> list[ProductResult]

Input and output are list[ProductResult] — never list[dict].
The relevance_score field on each returned result is replaced with the
cross-encoder score so downstream callers see a consistent field name.
"""

import logging

from flashrank import Ranker, RerankRequest

from app.schemas.search import ProductResult

log = logging.getLogger(__name__)

# ms-marco-MiniLM-L-12-v2: 33 MB, strong MS MARCO accuracy, fast on CPU.
# TinyBERT-L-2-v2 is faster but noticeably weaker on product queries.
_MODEL_NAME = "ms-marco-MiniLM-L-12-v2"

_ranker: Ranker | None = None


def _get_ranker() -> Ranker:
    global _ranker
    if _ranker is None:
        log.info("Loading flashrank model '%s'", _MODEL_NAME)
        _ranker = Ranker(model_name=_MODEL_NAME)
    return _ranker


def _passage_text(result: ProductResult) -> str:
    """Build a passage string the cross-encoder can score against the query."""
    parts = [f"{result.brand} {result.name}."]
    if result.category:
        parts.append(f"Category: {result.category}.")
    if result.use_cases:
        parts.append("Use cases: " + ", ".join(result.use_cases) + ".")
    specs = result.specs
    spec_parts = []
    if specs.get("ram_gb"):
        spec_parts.append(f"{specs['ram_gb']}GB RAM")
    if specs.get("storage_gb"):
        spec_parts.append(f"{specs['storage_gb']}GB storage")
    if specs.get("processor"):
        spec_parts.append(str(specs["processor"]))
    if specs.get("gpu"):
        spec_parts.append(str(specs["gpu"]))
    if spec_parts:
        parts.append(", ".join(spec_parts) + ".")
    return " ".join(parts)


def rerank(
    query: str,
    candidates: list[ProductResult],
    top_k: int = 10,
) -> list[ProductResult]:
    """
    Re-score candidates against query using a cross-encoder.
    Returns top_k results with updated relevance_score, sorted descending.
    Falls back to the original cosine-ranked list if reranking fails.
    """
    if not candidates:
        return []

    passages = [
        {"id": i, "text": _passage_text(result)}
        for i, result in enumerate(candidates)
    ]

    try:
        ranked = _get_ranker().rerank(RerankRequest(query=query, passages=passages))
    except Exception as exc:
        log.warning("Reranker failed, returning cosine order: %s", exc)
        return candidates[:top_k]

    # ranked is sorted descending by score; slice to top_k then update scores
    results: list[ProductResult] = []
    for entry in ranked[:top_k]:
        original = candidates[entry["id"]]
        results.append(original.model_copy(update={"relevance_score": float(entry["score"])}))

    return results
