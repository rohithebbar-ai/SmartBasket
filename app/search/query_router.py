"""
Query type router — classifies every incoming query as SEMANTIC, ANALYTICAL, or HYBRID.

Public interface:
    classify_query(query: str) -> QueryRouterOutput

Uses Bedrock Haiku (~150ms) with QUERY_ROUTER_PROMPT.  The LLM response is
parsed immediately into QueryRouterOutput — if the model returns an unexpected
type string, Pydantic raises ValidationError at the boundary so callers can
retry rather than propagate garbage.

Results are cached in Redis for ROUTER_CACHE_TTL seconds so repeated identical
queries (common in chat UIs with autocomplete) never hit Bedrock twice.

Called by:
  - app/search/router.py  (direct /api/search endpoint)
  - app/agent/nodes/route_query.py  (inside LangGraph)
"""

import hashlib
import logging

from pydantic import ValidationError

from app.agent.prompts import QUERY_ROUTER_PROMPT, QUERY_TYPE_ROUTER_PROMPT
from app.llm import call_llm
from app.redis_client import get_redis_client
from app.schemas.llm import QueryRouterOutput

log = logging.getLogger(__name__)

ROUTER_CACHE_TTL = 300  # seconds — same query twice within 5 min skips the LLM

# ── Cache helpers ──────────────────────────────────────────────────────────────

def _cache_key(query: str) -> str:
    digest = hashlib.sha256(query.lower().strip().encode()).hexdigest()[:16]
    return f"query_router:{digest}"


async def _get_cached(query: str) -> QueryRouterOutput | None:
    redis = get_redis_client()
    raw = await redis.get(_cache_key(query))
    if raw is None:
        return None
    try:
        return QueryRouterOutput.model_validate_json(raw)
    except Exception as exc:
        log.warning("Corrupt query_router cache value, treating as miss: %s", exc)
        return None


async def _set_cached(query: str, result: QueryRouterOutput) -> None:
    redis = get_redis_client()
    await redis.setex(_cache_key(query), ROUTER_CACHE_TTL, result.model_dump_json())


# ── Core classifier ────────────────────────────────────────────────────────────

async def classify_query(query: str, history: str = "") -> QueryRouterOutput:
    """
    Returns QueryRouterOutput with type SEMANTIC | ANALYTICAL | HYBRID.
    Raises ValidationError if LLM returns an unexpected value — caller retries.
    Cache hit (TTL=300s) skips Bedrock entirely.

    history: optional prior-turn context (agent graph only). When provided,
    uses QUERY_TYPE_ROUTER_PROMPT (history-aware) instead of QUERY_ROUTER_PROMPT.
    Cache is keyed on query only — history is not included so identical queries
    share cache hits across turns.
    """
    cached = await _get_cached(query)
    if cached is not None:
        log.debug("Query router cache hit: %.60s", query)
        return cached

    if history:
        prompt = QUERY_TYPE_ROUTER_PROMPT.format(history=history, message=query)
    else:
        prompt = QUERY_ROUTER_PROMPT.format(query=query)
    raw = await call_llm(prompt, tier="fast", max_tokens=150, temperature=0.0)

    result = QueryRouterOutput.model_validate_json(raw)

    await _set_cached(query, result)
    log.info("Query router: '%.60s' → %s", query, result.type)
    return result
