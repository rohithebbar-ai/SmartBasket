"""
visual_search — VISUAL intent path (image-based product discovery).

Flow:
  1. Read image_b64 from state.visual_attributes.
  2. Fetch filterable attribute candidates from Redis.
  3. Call CLIP service to classify image attributes (colour, category, pattern, …).
  4. Build a rewritten_query from top CLIP predictions.
  5. Embed the query and search the catalogue's Qdrant collection.
  6. Return search_results for synthesise to render.

Outgoing edge: → save_history  (visual search always goes straight to history;
  synthesis is skipped because the result list is rendered by the frontend).
"""

import asyncio
import logging

import httpx

from app.agent.state import ShopSenseState
from app.config import settings
from app.redis_client import get_redis_client
from app.search.catalogue_config import get_catalogue
from app.search.embedder import embed
from app.search.qdrant_ops import search
from app.search.reranker import rerank

log = logging.getLogger(__name__)

_GRACEFUL_STUB = (
    "Visual search is coming soon! In the meantime, describe what you're looking for "
    "— colour, style, occasion — and I'll find the best matches for you."
)


async def visual_search(state: ShopSenseState) -> dict:
    try:
        return await _visual_search(state)
    except Exception as exc:
        log.warning("visual_search failed unexpectedly (%s) — returning stub", exc)
        return {"final_response": _GRACEFUL_STUB}


async def _visual_search(state: ShopSenseState) -> dict:
    # ── 1. Read image_b64 ─────────────────────────────────────────────────────
    image_b64: str = state.get("visual_attributes", {}).get("image_b64", "")
    if not image_b64:
        return {"final_response": _GRACEFUL_STUB}

    # ── 2. Resolve catalogue config ───────────────────────────────────────────
    try:
        config = get_catalogue(state.get("catalogue") or "fashion")
    except Exception:
        config = get_catalogue("fashion")

    # ── 3. Fetch attribute candidates from Redis ──────────────────────────────
    candidates: dict[str, list[str]] = {}
    try:
        redis = get_redis_client()
        for attr in config.filterable_attrs:
            if not attr.is_qdrant_filter:
                continue
            try:
                raw = await redis.smembers(attr.redis_values_key)
                if raw:
                    candidates[attr.key] = [v if isinstance(v, str) else v.decode() for v in raw]
            except Exception as exc:
                log.debug("Redis smembers failed for key %s (%s) — skipping attr", attr.redis_values_key, exc)
    except Exception as exc:
        log.warning("Redis unavailable (%s) — calling CLIP with empty candidates", exc)

    # ── 4. Call CLIP service ──────────────────────────────────────────────────
    clip_top: dict = {}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{settings.clip_service_url}/classify",
                headers={"X-API-Key": settings.clip_service_api_key},
                json={"image_b64": image_b64, "candidates": candidates},
            )
            resp.raise_for_status()
            clip_result = resp.json()
            clip_top = {k: v for k, v in clip_result.get("top", {}).items() if v is not None}
    except Exception as exc:
        log.warning("CLIP service call failed (%s) — returning stub", exc)
        return {"final_response": _GRACEFUL_STUB}

    # ── 5. Build rewritten_query ──────────────────────────────────────────────
    rewritten_query = " ".join(str(v) for v in clip_top.values() if v) or "clothing"

    # ── 6. Store enriched visual_attributes ───────────────────────────────────
    visual_attributes = {
        **state.get("visual_attributes", {}),
        "clip_top": clip_top,
        "rewritten_query": rewritten_query,
    }

    # ── 7. Semantic search via Qdrant ─────────────────────────────────────────
    try:
        vector: list[float] = await asyncio.to_thread(embed, rewritten_query)
        candidates_raw = await asyncio.to_thread(
            search, vector, None, 20,
            config.sentiment_fields, config.qdrant_collection,
        )
        reranked = await asyncio.to_thread(rerank, rewritten_query, candidates_raw, 10)
        results = [r.model_dump() for r in reranked]
    except Exception as exc:
        log.warning("Qdrant search failed in visual_search (%s) — returning stub", exc)
        return {"final_response": _GRACEFUL_STUB}

    return {
        "search_results": results,
        "visual_attributes": visual_attributes,
        "extracted_filters": {"use_case": "visual_search"},
    }
