"""
compare_products — COMPARE intent path.

Steps:
  1. Extract 2-3 product names from the user message via LLM (fast tier).
  2. For each name, embed and search Qdrant (top-1) to find the closest match.
  3. Enrich each Qdrant match from PostgreSQL:
       - Fresh current_price, stock_count, description
       - JSONB attributes: colour, pattern, garment_group, section
       - Aggregated fashion sentiment averages (style, quality, fit, comfort, versatility)
     Falls back to the Qdrant result as-is if the DB fetch fails.
  4. Writes state.query_type = "COMPARE" so synthesise uses COMPARISON_SYNTHESIS_PROMPT.
  5. Falls back to broad semantic search when extraction fails or finds nothing.

Reads:  state.messages (last user message), state.catalogue
Writes: state.search_results, state.sources, state.query_type ("COMPARE")

Outgoing edge: → synthesise (bypasses personalise — deterministic fetch)
"""

import asyncio
import json
import logging

from sqlalchemy import text

from app.agent.prompts import COMPARE_EXTRACTION_PROMPT, OCCASION_EXTRACTION_PROMPT
from app.agent.state import ShopSenseState
from app.database import AsyncSessionLocal
from app.llm import call_llm
from app.schemas.search import ProductResult
from app.search.embedder import embed
from app.search.qdrant_ops import search

log = logging.getLogger(__name__)

# Fetches fresh price/stock, JSONB attributes, and aggregated fashion sentiment.
# Sentiment columns are averaged across all reviews — not LIMIT 1 (would grab one random row).
_ENRICH_SQL = text("""
    SELECT
        p.id,
        p.name,
        p.brand,
        p.category,
        CAST(p.current_price AS FLOAT)       AS current_price,
        p.avg_rating,
        p.stock_count,
        p.description,
        p.attributes,
        AVG(p.style_sentiment)               AS style_sentiment,
        AVG(p.quality_sentiment)             AS quality_sentiment,
        AVG(p.fit_sentiment)                 AS fit_sentiment,
        AVG(p.comfort_sentiment)             AS comfort_sentiment,
        AVG(p.versatility_sentiment)         AS versatility_sentiment
    FROM products p
    WHERE p.id = :product_id
    GROUP BY p.id, p.name, p.brand, p.category, p.current_price,
             p.avg_rating, p.stock_count, p.description, p.attributes
""")


async def _find_product_in_qdrant(name: str) -> ProductResult | None:
    """Embed a product name and return the top-1 Qdrant result."""
    try:
        vector = await asyncio.to_thread(embed, name)
        results = await asyncio.to_thread(search, vector, None, 1)
        return results[0] if results else None
    except Exception as exc:
        log.warning("Qdrant lookup failed for %r: %s", name, exc)
        return None


async def _enrich_from_db(product_id: str, qdrant_result: ProductResult) -> ProductResult:
    """
    Fetch fresh price/stock and aggregated sentiment from PostgreSQL.
    Returns the enriched ProductResult, or the original Qdrant result on failure.
    """
    try:
        async with AsyncSessionLocal() as db:
            row = (await db.execute(_ENRICH_SQL, {"product_id": product_id})).mappings().first()

        if row is None:
            return qdrant_result

        _SENTIMENT_COLS = (
            "style_sentiment", "quality_sentiment", "fit_sentiment",
            "comfort_sentiment", "versatility_sentiment",
        )
        sentiment_scores = {
            k: round(float(row[k]), 2)
            for k in _SENTIMENT_COLS
            if row[k] is not None
        }

        # attributes JSONB → colour, pattern, garment_group, section, department
        raw_attrs = row["attributes"]
        if isinstance(raw_attrs, str):
            try:
                attrs: dict = json.loads(raw_attrs)
            except json.JSONDecodeError:
                attrs = {}
        elif isinstance(raw_attrs, dict):
            attrs = raw_attrs
        else:
            attrs = {}

        return ProductResult(
            product_id=product_id,
            name=row["name"],
            brand=row["brand"],
            category=row["category"],
            current_price=float(row["current_price"]),
            avg_rating=float(row["avg_rating"]),
            relevance_score=qdrant_result.relevance_score,
            stock_available=int(row["stock_count"]) > 0,
            description=row["description"] or "",
            attributes=attrs,
            sentiment_scores=sentiment_scores,
            use_cases=qdrant_result.use_cases,
        )
    except Exception as exc:
        log.warning("DB enrichment failed for product %s (%s) — using Qdrant result", product_id, exc)
        return qdrant_result


async def compare_products(state: ShopSenseState) -> dict:
    messages = state.get("messages", [])
    query = messages[-1]["content"] if messages else ""

    # Step 1 — Extract product names via LLM
    product_names: list[str] = []
    try:
        raw = await call_llm(
            COMPARE_EXTRACTION_PROMPT.format(message=query),
            tier="fast",
            max_tokens=100,
            temperature=0.0,
        )
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            product_names = [str(n) for n in parsed if isinstance(n, str)][:3]
    except Exception as exc:
        log.warning("Product name extraction failed (%s) — falling back to broad search", exc)

    # Step 2 — Find each product in Qdrant (parallel)
    found: list[ProductResult] = []
    if product_names:
        qdrant_results = await asyncio.gather(
            *[_find_product_in_qdrant(name) for name in product_names]
        )

        seen_ids: set[str] = set()
        candidates: list[ProductResult] = []
        for result in qdrant_results:
            if result and result.product_id not in seen_ids:
                candidates.append(result)
                seen_ids.add(result.product_id)

        # Step 3 — Enrich each Qdrant match from PostgreSQL (parallel)
        if candidates:
            found = list(await asyncio.gather(
                *[_enrich_from_db(r.product_id, r) for r in candidates]
            ))

    # Fallback — broad semantic search when extraction failed or found nothing
    if not found:
        log.warning("compare_products: no named products found — running broad search on full query")
        try:
            vector = await asyncio.to_thread(embed, query)
            candidates_fb = await asyncio.to_thread(search, vector, None, 3)
            if candidates_fb:
                found = list(await asyncio.gather(
                    *[_enrich_from_db(r.product_id, r) for r in candidates_fb[:3]]
                ))
        except Exception as exc:
            log.error("compare_products fallback search failed: %s", exc)

    # Extract occasion/use-case from the query so synthesise can lead with it
    occasion = ""
    try:
        raw_occ = await call_llm(
            OCCASION_EXTRACTION_PROMPT.format(message=query),
            tier="fast",
            max_tokens=30,
            temperature=0.0,
        )
        occasion = raw_occ.strip().strip('"').strip("'")
    except Exception:
        pass

    return {
        "search_results": [r.model_dump() for r in found],
        "sources": [r.product_id for r in found],
        "query_type": "COMPARE",
        "occasion_context": occasion,
    }
