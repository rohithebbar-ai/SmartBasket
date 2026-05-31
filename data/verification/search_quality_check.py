"""
Semantic search quality check — runs 15 representative queries against the
Qdrant-backed product index and reports per-query relevance scores plus a
summary so you can spot embedding or indexing regressions at a glance.

Usage:
    python data/verification/search_quality_check.py

Prerequisites:
    - QDRANT_URL (and optionally QDRANT_API_KEY, JINA_API_KEY / NVIDIA_API_KEY)
      must be set in the project-root .env file.
    - The Qdrant collection must already be populated.
"""

import sys
import time
from pathlib import Path

# ── Environment must be loaded before any app.* import ───────────────────────
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# ── App imports (after env is ready) ─────────────────────────────────────────
try:
    from app.search.embedder import embed
    from app.search.qdrant_ops import search
    from app.schemas.search import ProductResult
except ImportError as exc:
    sys.exit(
        f"Import error: {exc}\n"
        "Make sure you are running from the project root with the virtualenv active."
    )

# ── Constants ─────────────────────────────────────────────────────────────────

TOP_K = 5
LOW_SCORE_THRESHOLD = 0.60

QUERIES: list[str] = [
    "floral summer dress",
    "something for a beach wedding",
    "casual wear for work from home",
    "formal evening outfit",
    "sustainable fashion",
    "oversized cosy knit",
    "gym activewear",
    "office smart casual",
    "date night outfit",
    "gift for teenage girl",
    "warm winter coat",
    "lightweight jacket for spring",
    "party dress",
    "comfortable everyday basics",
    "classic denim look",
]

DIVIDER_THIN = "━" * 50
DIVIDER_THICK = "═" * 33


# ── Display helpers ───────────────────────────────────────────────────────────

def _format_price(price: float) -> str:
    return f"${price:.2f}"


def _print_query_header(query: str) -> None:
    print(f"\n{DIVIDER_THIN}")
    print(f'Query: "{query}"')
    print(DIVIDER_THIN)


def _print_result_row(rank: int, result: ProductResult) -> None:
    price = _format_price(result.current_price)
    print(
        f"  {rank}. [{result.relevance_score:.3f}] "
        f"{result.name} — {result.category} — {price}"
    )


# ── Core logic ────────────────────────────────────────────────────────────────

def run_single_query(query: str) -> list[ProductResult]:
    """Embed query and retrieve top-K results from Qdrant."""
    vector = embed(query)
    return search(query_vector=vector, filters=None, top_k=TOP_K)


def run_all_queries() -> dict[str, list[ProductResult]]:
    """
    Run every query in QUERIES and return a mapping of query -> results.

    Raises ConnectionError with a user-friendly message if Qdrant is
    unreachable, so the caller can surface it cleanly.
    """
    results_by_query: dict[str, list[ProductResult]] = {}

    for query in QUERIES:
        try:
            results_by_query[query] = run_single_query(query)
        except Exception as exc:
            # Surface connection/API errors immediately — don't silently skip.
            error_text = str(exc).lower()
            if any(kw in error_text for kw in ("connect", "timeout", "refused", "url")):
                raise ConnectionError(
                    f"Could not reach Qdrant for query '{query}'.\n"
                    "Is Qdrant running? Check QDRANT_URL in .env"
                ) from exc
            raise

    return results_by_query


def print_query_results(query: str, results: list[ProductResult]) -> None:
    _print_query_header(query)
    if not results:
        print("  (no results returned)")
        return
    for rank, result in enumerate(results, start=1):
        _print_result_row(rank, result)


def _top1_score(results: list[ProductResult]) -> float | None:
    """Return the relevance_score of the first result, or None if empty."""
    return results[0].relevance_score if results else None


def print_summary(results_by_query: dict[str, list[ProductResult]], elapsed: float) -> None:
    top1_scores: list[tuple[str, float]] = [
        (query, score)
        for query, results in results_by_query.items()
        if (score := _top1_score(results)) is not None
    ]

    if not top1_scores:
        print(f"\n{DIVIDER_THICK}")
        print("No results returned for any query.")
        print(DIVIDER_THICK)
        return

    scores_only = [score for _, score in top1_scores]
    avg_score = sum(scores_only) / len(scores_only)
    min_query, min_score = min(top1_scores, key=lambda t: t[1])
    max_query, max_score = max(top1_scores, key=lambda t: t[1])
    low_count = sum(1 for s in scores_only if s < LOW_SCORE_THRESHOLD)

    print(f"\n{DIVIDER_THICK}")
    print(f"Total queries:              {len(QUERIES)}")
    print(f"Avg top-1 score:            {avg_score:.3f}")
    print(f'Min top-1 score:            {min_score:.3f}  (query: "{min_query}")')
    print(f'Max top-1 score:            {max_score:.3f}  (query: "{max_query}")')
    print(f"Queries with top-1 < {LOW_SCORE_THRESHOLD:.2f}:   {low_count}")
    print(DIVIDER_THICK)
    print(f"Total elapsed: {elapsed:.2f}s")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    start = time.perf_counter()

    try:
        results_by_query = run_all_queries()
    except ConnectionError as exc:
        sys.exit(str(exc))

    for query, results in results_by_query.items():
        print_query_results(query, results)

    elapsed = time.perf_counter() - start
    print_summary(results_by_query, elapsed)


if __name__ == "__main__":
    main()
