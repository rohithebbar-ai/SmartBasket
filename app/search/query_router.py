"""
Query type router — classifies every incoming query as SEMANTIC, ANALYTICAL, or HYBRID.

Public interface:
    classify_query(query: str, history: str = "", config: CatalogueConfig | None = None) -> QueryRouterOutput

Uses Bedrock Haiku (~150ms) with QUERY_ROUTER_PROMPT.  The LLM response is
parsed immediately into QueryRouterOutput — if the model returns an unexpected
type string, Pydantic raises ValidationError at the boundary so callers can
retry rather than propagate garbage.

Results are cached in Redis for ROUTER_CACHE_TTL seconds so repeated identical
queries (common in chat UIs with autocomplete) never hit Bedrock twice.
Cache key includes client_id so fashion and electronics queries never share hits.

Called by:
  - app/search/router.py  (direct /api/search endpoint)
  - app/agent/nodes/route_query.py  (inside LangGraph)
"""
from __future__ import annotations

import hashlib
import logging

from pydantic import ValidationError

from app.agent.prompts import QUERY_ROUTER_PROMPT, QUERY_TYPE_ROUTER_PROMPT
from app.llm import call_llm
from app.redis_client import get_redis_client
from app.schemas.llm import QueryRouterOutput
from app.search.catalogue_config import CatalogueConfig

log = logging.getLogger(__name__)

ROUTER_CACHE_TTL = 300  # seconds — same query twice within 5 min skips the LLM

# ── Cache helpers ──────────────────────────────────────────────────────────────

def _cache_key(query: str, client_id: str = "default") -> str:
    digest = hashlib.sha256(f"{client_id}:{query.lower().strip()}".encode()).hexdigest()[:16]
    return f"query_router:{digest}"


async def _get_cached(query: str, client_id: str = "default") -> QueryRouterOutput | None:
    redis = get_redis_client()
    raw = await redis.get(_cache_key(query, client_id))
    if raw is None:
        return None
    try:
        return QueryRouterOutput.model_validate_json(raw)
    except Exception as exc:
        log.warning("Corrupt query_router cache value, treating as miss: %s", exc)
        return None


async def _set_cached(query: str, result: QueryRouterOutput, client_id: str = "default") -> None:
    redis = get_redis_client()
    await redis.setex(_cache_key(query, client_id), ROUTER_CACHE_TTL, result.model_dump_json())


# ── Prompt builder ─────────────────────────────────────────────────────────────

def _build_router_prompt(query: str, routing_examples: list[tuple[str, str]]) -> str:
    examples = "\n".join(f'  "{q}" → {route}' for q, route in routing_examples)
    return (
        "Classify this shopping query into exactly one category.\n\n"
        "Categories:\n"
        "- SEMANTIC: Discovery query, exploratory, needs meaning not structure.\n"
        "- ANALYTICAL: Structured data question, needs exact numbers or aggregations.\n"
        "- HYBRID: Needs both semantic understanding AND structured filters.\n\n"
        f"Examples:\n{examples}\n\n"
        f"Query: {query}\n\n"
        "Respond with JSON only — no markdown, no explanation outside the JSON:\n"
        '{"type": "SEMANTIC", "reasoning": "..."}'
    )


# ── Core classifier ────────────────────────────────────────────────────────────

async def classify_query(
    query: str,
    history: str = "",
    config: CatalogueConfig | None = None,
) -> QueryRouterOutput:
    """
    Returns QueryRouterOutput with type SEMANTIC | ANALYTICAL | HYBRID.
    Raises ValidationError if LLM returns an unexpected value — caller retries.
    Cache hit (TTL=300s) skips Bedrock entirely.

    config: when provided, routing_examples from the catalogue replace the
    hardcoded electronics few-shot examples and the cache key is scoped to
    config.client_id so catalogues never share hits.

    history: optional prior-turn context (agent graph only). Ignored when
    config is provided — the catalogue-specific prompt takes precedence.
    """
    client_id = config.client_id if config else "default"
    cached = await _get_cached(query, client_id)
    if cached is not None:
        log.debug("Query router cache hit [%s]: %.60s", client_id, query)
        return cached

    if config:
        prompt = _build_router_prompt(query, config.routing_examples)
    elif history:
        prompt = QUERY_TYPE_ROUTER_PROMPT.format(history=history, message=query)
    else:
        prompt = QUERY_ROUTER_PROMPT.format(query=query)

    raw = await call_llm(prompt, tier="fast", max_tokens=150, temperature=0.0)
    result = QueryRouterOutput.model_validate_json(raw)

    await _set_cached(query, result, client_id)
    log.info("Query router [%s]: '%.60s' → %s", client_id, query, result.type)
    return result
