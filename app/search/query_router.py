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

import asyncio
import hashlib
import logging

import boto3
from pydantic import ValidationError

from app.agent.prompts import QUERY_ROUTER_PROMPT
from app.config import settings
from app.redis_client import get_redis_client
from app.schemas.llm import QueryRouterOutput

log = logging.getLogger(__name__)

ROUTER_CACHE_TTL = 300  # seconds — same query twice within 5 min skips Bedrock

# ── Bedrock client singleton ───────────────────────────────────────────────────

_bedrock = None


def _get_bedrock():
    global _bedrock
    if _bedrock is None:
        if settings.aws_profile:
            session = boto3.Session(profile_name=settings.aws_profile)
            _bedrock = session.client("bedrock-runtime", region_name=settings.aws_region)
        else:
            kwargs: dict = {"region_name": settings.aws_region}
            if settings.aws_access_key_id and settings.aws_secret_access_key:
                kwargs["aws_access_key_id"] = settings.aws_access_key_id
                kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
            _bedrock = boto3.client("bedrock-runtime", **kwargs)
    return _bedrock


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


# ── Bedrock call (sync, runs in thread pool) ───────────────────────────────────

def _call_bedrock(prompt: str) -> str:
    response = _get_bedrock().converse(
        modelId=settings.bedrock_fast_model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={
            "maxTokens": 150,
            "temperature": 0.0,  # deterministic classification
        },
    )
    text = response["output"]["message"]["content"][0]["text"].strip()
    # Haiku wraps JSON in ```json ... ``` fences despite instructions — strip them.
    if text.startswith("```"):
        text = text.split("```", 2)[1]         # drop opening fence line
        if text.startswith("json"):
            text = text[4:]                    # drop language tag
        text = text.rsplit("```", 1)[0].strip()
    return text


# ── Core classifier ────────────────────────────────────────────────────────────

async def classify_query(query: str) -> QueryRouterOutput:
    """
    Returns QueryRouterOutput with type SEMANTIC | ANALYTICAL | HYBRID.
    Raises ValidationError if LLM returns an unexpected value — caller retries.
    Cache hit (TTL=300s) skips Bedrock entirely.
    """
    cached = await _get_cached(query)
    if cached is not None:
        log.debug("Query router cache hit: %.60s", query)
        return cached

    prompt = QUERY_ROUTER_PROMPT.format(query=query)
    raw = await asyncio.to_thread(_call_bedrock, prompt)

    result = QueryRouterOutput.model_validate_json(raw)

    await _set_cached(query, result)
    log.info("Query router: '%.60s' → %s", query, result.type)
    return result
