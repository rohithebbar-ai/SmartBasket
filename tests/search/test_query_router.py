"""
Tests for app/search/query_router.py

Strategy:
- All LLM calls are patched — no provider credentials needed.
- Redis calls are patched to control cache hit/miss behaviour.
- ValidationError propagation test ensures LLM hallucinations are caught at boundary.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.schemas.llm import QueryRouterOutput


# ── Helpers ───────────────────────────────────────────────────────────────────

def _llm_response(query_type: str, reasoning: str = "test reasoning") -> str:
    return json.dumps({"type": query_type, "reasoning": reasoning})


def _mock_redis(cached_value: str | None = None):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=cached_value)
    redis.setex = AsyncMock()
    return redis


# ── Classification accuracy ───────────────────────────────────────────────────

class TestQueryRouterClassification:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("query,expected_type", [
        # SEMANTIC — discovery / exploratory
        ("laptop for video editing", "SEMANTIC"),
        ("something portable for travel", "SEMANTIC"),
        ("what do you recommend for a developer", "SEMANTIC"),
        ("good gaming laptop", "SEMANTIC"),
        # ANALYTICAL — structured / aggregation
        ("which brand has highest ratings", "ANALYTICAL"),
        ("show out of stock products", "ANALYTICAL"),
        ("average price of Dell laptops", "ANALYTICAL"),
        ("how many laptops are under 50k", "ANALYTICAL"),
        # HYBRID — semantic + structured filter
        ("best reviewed laptop under 80k with good battery", "HYBRID"),
        ("top rated Dell products for video editing", "HYBRID"),
        ("affordable options with high display ratings", "HYBRID"),
    ])
    async def test_classify_returns_correct_type(self, query: str, expected_type: str):
        mock_redis = _mock_redis(cached_value=None)
        raw = _llm_response(expected_type)

        with (
            patch("app.search.query_router.get_redis_client", return_value=mock_redis),
            patch("app.search.query_router.call_llm", new_callable=AsyncMock, return_value=raw),
        ):
            from app.search.query_router import classify_query
            result = await classify_query(query)

        assert result.type == expected_type
        assert isinstance(result.reasoning, str)
        assert len(result.reasoning) > 0

    @pytest.mark.asyncio
    async def test_result_is_query_router_output_instance(self):
        mock_redis = _mock_redis(cached_value=None)
        raw = _llm_response("SEMANTIC")

        with (
            patch("app.search.query_router.get_redis_client", return_value=mock_redis),
            patch("app.search.query_router.call_llm", new_callable=AsyncMock, return_value=raw),
        ):
            from app.search.query_router import classify_query
            result = await classify_query("good laptop for students")

        assert isinstance(result, QueryRouterOutput)


# ── Redis caching ─────────────────────────────────────────────────────────────

class TestQueryRouterCaching:
    @pytest.mark.asyncio
    async def test_cache_miss_calls_bedrock_and_writes_cache(self):
        mock_redis = _mock_redis(cached_value=None)
        raw = _llm_response("SEMANTIC", "exploratory query")

        with (
            patch("app.search.query_router.get_redis_client", return_value=mock_redis),
            patch("app.search.query_router.call_llm", new_callable=AsyncMock, return_value=raw) as mock_llm,
        ):
            from app.search.query_router import classify_query
            result = await classify_query("laptop for travel")

        mock_llm.assert_called_once()
        mock_redis.setex.assert_called_once()
        assert result.type == "SEMANTIC"

    @pytest.mark.asyncio
    async def test_cache_hit_skips_bedrock(self):
        cached = QueryRouterOutput(type="HYBRID", reasoning="cached result")
        mock_redis = _mock_redis(cached_value=cached.model_dump_json())

        with (
            patch("app.search.query_router.get_redis_client", return_value=mock_redis),
            patch("app.search.query_router.call_llm", new_callable=AsyncMock) as mock_llm,
        ):
            from app.search.query_router import classify_query
            result = await classify_query("best laptop under 80k")

        mock_llm.assert_not_called()
        assert result.type == "HYBRID"

    @pytest.mark.asyncio
    async def test_cache_ttl_is_set_correctly(self):
        mock_redis = _mock_redis(cached_value=None)
        raw = _llm_response("ANALYTICAL")

        with (
            patch("app.search.query_router.get_redis_client", return_value=mock_redis),
            patch("app.search.query_router.call_llm", new_callable=AsyncMock, return_value=raw),
        ):
            from app.search.query_router import classify_query, ROUTER_CACHE_TTL
            await classify_query("which brand has highest avg rating")

        call_args = mock_redis.setex.call_args
        ttl_arg = call_args[0][1]
        assert ttl_arg == ROUTER_CACHE_TTL

    @pytest.mark.asyncio
    async def test_corrupt_cache_falls_through_to_bedrock(self):
        """A corrupted cache value must not crash — fall through to the LLM."""
        mock_redis = _mock_redis(cached_value="not-valid-json{{")
        raw = _llm_response("SEMANTIC")

        with (
            patch("app.search.query_router.get_redis_client", return_value=mock_redis),
            patch("app.search.query_router.call_llm", new_callable=AsyncMock, return_value=raw) as mock_llm,
        ):
            from app.search.query_router import classify_query
            result = await classify_query("laptop for photo editing")

        mock_llm.assert_called_once()
        assert result.type == "SEMANTIC"

    @pytest.mark.asyncio
    async def test_different_queries_produce_different_cache_keys(self):
        """Each query must be cached under a distinct key."""
        from app.search.query_router import _cache_key

        key1 = _cache_key("gaming laptop")
        key2 = _cache_key("average price of dell")
        assert key1 != key2
        assert key1.startswith("query_router:")
        assert key2.startswith("query_router:")

    @pytest.mark.asyncio
    async def test_query_normalised_before_cache_key(self):
        """Leading/trailing whitespace and case differences hash to the same key."""
        from app.search.query_router import _cache_key

        assert _cache_key("Gaming Laptop") == _cache_key("gaming laptop")
        assert _cache_key("  gaming laptop  ") == _cache_key("gaming laptop")


# ── Validation error propagation ──────────────────────────────────────────────

class TestQueryRouterValidation:
    @pytest.mark.asyncio
    async def test_bad_llm_response_raises_validation_error(self):
        """If the LLM returns an unexpected type value, ValidationError must propagate."""
        mock_redis = _mock_redis(cached_value=None)
        bad_response = json.dumps({"type": "VECTOR_SEARCH", "reasoning": "made up"})

        with (
            patch("app.search.query_router.get_redis_client", return_value=mock_redis),
            patch("app.search.query_router.call_llm", new_callable=AsyncMock, return_value=bad_response),
        ):
            from app.search.query_router import classify_query
            with pytest.raises(ValidationError):
                await classify_query("laptop for gaming")

    @pytest.mark.asyncio
    async def test_non_json_llm_response_raises(self):
        """Prose instead of JSON must raise (not swallow the error)."""
        mock_redis = _mock_redis(cached_value=None)

        with (
            patch("app.search.query_router.get_redis_client", return_value=mock_redis),
            patch("app.search.query_router.call_llm", new_callable=AsyncMock, return_value="This is SEMANTIC because..."),
        ):
            from app.search.query_router import classify_query
            with pytest.raises(Exception):
                await classify_query("laptop for students")
