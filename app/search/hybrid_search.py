"""
Hybrid search — Reciprocal Rank Fusion of SQL + vector rankings.

Both ranking paths run independently and are merged with:
    rrf_score = 1/(k + sql_rank) + 1/(k + vector_rank),  k=60

Products that rank well in both lists float to the top. Products in only one
list still contribute via their single ranking term — no candidates are excluded.

Why RRF over SQL-constrains-then-vector:
  If SQL filters to 15 products, vector search has almost nothing to rank and
  quality collapses. RRF avoids this by running both paths on the full corpus
  and merging by combined rank.

Public interface:
    hybrid_search(query, db, top_k=10) -> list[ProductResult]
"""

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import call_llm
from app.schemas.search import ProductResult
from app.search.embedder import embed
from app.search.nl_to_sql import validate_sql
from app.search.qdrant_ops import search as qdrant_search

log = logging.getLogger(__name__)

RRF_K = 60


# ── Hybrid SQL prompt ─────────────────────────────────────────────────────────
# Different from the analytics prompt: the goal here is structured RANKING,
# not answering a question. The SQL must return id + product metadata ordered
# by structured relevance (avg_rating, sentiment columns, price constraints).

_HYBRID_SQL_PROMPT = """\
You are generating SQL for a HYBRID product search on ShopSense.

The query contains BOTH semantic intent AND structured constraints (price, brand,
rating, category, stock, quality signals like battery or display).

Task: generate a SELECT that:
1. Filters products by any explicit constraints in the query (brand, max_price,
   min_price, category, stock availability, min_rating).
2. Joins reviews when the query references quality signals (battery, display,
   build, value, performance) — use AVG of the relevant sentiment column in ORDER BY.
3. Orders results by structured relevance: p.avg_rating DESC, then the most
   relevant sentiment column DESC NULLS LAST.
4. Returns exactly these columns: id, name, brand, category, current_price,
   avg_rating, stock_count.
5. Always adds LIMIT 50.

Schema:
  products(id UUID PK, name VARCHAR, brand VARCHAR, category VARCHAR,
           base_price DECIMAL, current_price DECIMAL, specs JSONB,
           stock_count INTEGER, avg_rating FLOAT, is_active BOOLEAN)

  reviews(id UUID PK, product_id UUID FK->products.id,
          battery_sentiment FLOAT, display_sentiment FLOAT,
          build_quality_sentiment FLOAT, value_sentiment FLOAT,
          performance_sentiment FLOAT)

Rules:
- SELECT only. Always filter is_active = true. Always add LIMIT 50.
- If joining reviews: LEFT JOIN reviews r ON r.product_id = p.id,
  then GROUP BY p.id, p.name, p.brand, p.category, p.current_price,
  p.avg_rating, p.stock_count.
- Return SQL only — no markdown, no code fences, no explanation.

Query: {query}"""


async def _generate_hybrid_sql(query: str) -> str:
    """Generate ranking SQL for the hybrid path via the central LLM gateway."""
    prompt = _HYBRID_SQL_PROMPT.format(query=query)
    return await call_llm(prompt, tier="fast", max_tokens=400, temperature=0.0)


# ── SQL ranking path ──────────────────────────────────────────────────────────

async def _sql_ranking(query: str, db: AsyncSession) -> list[dict]:
    """
    Generate and execute a structured ranking SQL for the hybrid query.
    Returns rows ordered by structured relevance (avg_rating, sentiment, filters).
    Returns [] on any failure — the vector path runs independently and RRF
    degrades gracefully to vector-only if this path fails.
    """
    try:
        sql = await _generate_hybrid_sql(query)
    except Exception as exc:
        log.warning("Hybrid SQL generation failed (non-fatal): %s", exc)
        return []

    valid, error = validate_sql(sql)
    if not valid:
        log.warning(
            "Hybrid SQL failed validation (non-fatal): %s | SQL: %.120s", error, sql
        )
        return []

    try:
        result = await db.execute(text(sql))
        keys = list(result.keys())
        rows = [dict(zip(keys, row)) for row in result.fetchall()]

        if not rows:
            return []

        # Normalise: model may return 'product_id' instead of 'id'
        if "id" not in rows[0] and "product_id" in rows[0]:
            for row in rows:
                row["id"] = row["product_id"]

        if "id" not in rows[0]:
            log.warning("Hybrid SQL returned no id/product_id column — skipping SQL path")
            return []

        log.info("Hybrid SQL ranking: %d products for query: %.60s", len(rows), query)
        return rows
    except Exception as exc:
        log.warning(
            "Hybrid SQL execution failed (non-fatal): %s | SQL: %.200s", exc, sql
        )
        return []


# ── Vector ranking path ───────────────────────────────────────────────────────

def _vector_ranking_sync(query: str) -> list[ProductResult]:
    """Embed query and search full Qdrant collection (sync — called via asyncio.to_thread)."""
    vector = embed(query)
    # No filter — search the full corpus so RRF can score against SQL candidates
    return qdrant_search(query_vector=vector, filters=None, top_k=50)


# ── RRF merge ─────────────────────────────────────────────────────────────────

def _rrf_merge(
    sql_rows: list[dict],
    vector_results: list[ProductResult],
    top_k: int,
) -> list[ProductResult]:
    """
    Merge SQL and vector rankings using Reciprocal Rank Fusion.

        rrf_score = 1/(k + sql_rank) + 1/(k + vector_rank),  k=60

    Products in only one list contribute via their single term (the other term
    is simply absent — they are not penalised with a worst-rank proxy).
    Sort descending by rrf_score, return top_k.
    """
    scores: dict[str, float] = {}

    for i, row in enumerate(sql_rows):
        pid = str(row.get("id") or row.get("product_id", ""))
        if pid:
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (RRF_K + i)

    for i, result in enumerate(vector_results):
        pid = result.product_id
        scores[pid] = scores.get(pid, 0.0) + 1.0 / (RRF_K + i)

    ranked_pids = sorted(scores, key=lambda p: scores[p], reverse=True)[:top_k]

    sql_by_id: dict[str, dict] = {}
    for row in sql_rows:
        pid = str(row.get("id") or row.get("product_id", ""))
        if pid:
            sql_by_id[pid] = row

    vector_by_id: dict[str, ProductResult] = {r.product_id: r for r in vector_results}

    results: list[ProductResult] = []
    for pid in ranked_pids:
        rrf_score = scores[pid]

        if pid in vector_by_id:
            # Prefer Qdrant payload — carries sentiment scores, specs, use_cases
            r = vector_by_id[pid]
            results.append(ProductResult(
                product_id=r.product_id,
                name=r.name,
                brand=r.brand,
                category=r.category,
                current_price=r.current_price,
                avg_rating=r.avg_rating,
                relevance_score=round(rrf_score, 6),
                stock_available=r.stock_available,
                specs=r.specs,
                sentiment_scores=r.sentiment_scores,
                use_cases=r.use_cases,
            ))
        elif pid in sql_by_id:
            # SQL-only product — outside Qdrant top-50; build from SQL row
            row = sql_by_id[pid]
            results.append(ProductResult(
                product_id=pid,
                name=row.get("name", ""),
                brand=row.get("brand", ""),
                category=row.get("category", ""),
                current_price=float(row.get("current_price") or 0.0),
                avg_rating=float(row.get("avg_rating") or 0.0),
                relevance_score=round(rrf_score, 6),
                stock_available=(row.get("stock_count") or 0) > 0,
            ))

    return results


# ── Public interface ──────────────────────────────────────────────────────────

async def hybrid_search(
    query: str,
    db: AsyncSession,
    top_k: int = 10,
) -> list[ProductResult]:
    """
    Run SQL ranking and vector ranking concurrently, merge with RRF.

    Args:
        query:  Natural-language hybrid query (semantic intent + structured filters).
        db:     AsyncSession for SQL execution.
        top_k:  Number of results to return after RRF merge.

    Returns:
        ProductResult list sorted by rrf_score descending.
        Degrades to vector-only if SQL path fails — never raises.
    """
    sql_rows, vector_results = await asyncio.gather(
        _sql_ranking(query, db),
        asyncio.to_thread(_vector_ranking_sync, query),
    )

    if not sql_rows and not vector_results:
        log.warning("Hybrid search: both paths returned empty for query: %.80s", query)
        return []

    results = _rrf_merge(sql_rows, vector_results, top_k)
    log.info(
        "Hybrid RRF: sql=%d vector=%d → top_%d=%d | query: %.60s",
        len(sql_rows), len(vector_results), top_k, len(results), query,
    )
    return results
