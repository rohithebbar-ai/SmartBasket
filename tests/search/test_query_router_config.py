"""
Tests for the config-driven path added in Day 20.

Covers:
- _build_router_prompt injects routing_examples correctly
- classify_query uses config prompt when config is provided
- Cache key isolation: same query, different catalogues → different keys
- Config path takes precedence over history
- Cache hit returns without hitting LLM (config path)
- Empty routing_examples does not crash
- Unknown query type from LLM still raises ValidationError on config path
- Cache normalisation still works with client_id
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.schemas.llm import QueryRouterOutput
from app.search.catalogue_config import FASHION_CATALOGUE, ELECTRONICS_CATALOGUE, CatalogueConfig, AttrDef


# ── Helpers ───────────────────────────────────────────────────────────────────

def _llm_response(query_type: str, reasoning: str = "test") -> str:
    return json.dumps({"type": query_type, "reasoning": reasoning})


def _mock_redis(cached_value: str | None = None):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=cached_value)
    redis.setex = AsyncMock()
    return redis


# ── _build_router_prompt ──────────────────────────────────────────────────────

class TestBuildRouterPrompt:
    def test_contains_all_routing_examples(self):
        from app.search.query_router import _build_router_prompt
        examples = [("show me red dresses", "SEMANTIC"), ("how many items in stock", "ANALYTICAL")]
        prompt = _build_router_prompt("test query", examples)
        assert '"show me red dresses" → SEMANTIC' in prompt
        assert '"how many items in stock" → ANALYTICAL' in prompt

    def test_contains_query(self):
        from app.search.query_router import _build_router_prompt
        prompt = _build_router_prompt("floral dress under $30", FASHION_CATALOGUE.routing_examples)
        assert "floral dress under $30" in prompt

    def test_contains_all_three_category_names(self):
        from app.search.query_router import _build_router_prompt
        prompt = _build_router_prompt("anything", FASHION_CATALOGUE.routing_examples)
        assert "SEMANTIC" in prompt
        assert "ANALYTICAL" in prompt
        assert "HYBRID" in prompt

    def test_empty_examples_does_not_crash(self):
        from app.search.query_router import _build_router_prompt
        prompt = _build_router_prompt("some query", [])
        assert "some query" in prompt
        assert "SEMANTIC" in prompt

    def test_fashion_and_electronics_prompts_differ(self):
        from app.search.query_router import _build_router_prompt
        fashion_prompt = _build_router_prompt("a query", FASHION_CATALOGUE.routing_examples)
        electronics_prompt = _build_router_prompt("a query", ELECTRONICS_CATALOGUE.routing_examples)
        assert fashion_prompt != electronics_prompt


# ── Cache key isolation ───────────────────────────────────────────────────────

class TestCacheKeyIsolation:
    def test_same_query_different_catalogue_produces_different_keys(self):
        from app.search.query_router import _cache_key
        key_fashion = _cache_key("show me blue dresses", "fashion")
        key_electronics = _cache_key("show me blue dresses", "electronics")
        assert key_fashion != key_electronics

    def test_same_query_same_catalogue_produces_same_key(self):
        from app.search.query_router import _cache_key
        assert _cache_key("floral dress", "fashion") == _cache_key("floral dress", "fashion")

    def test_default_client_id_differs_from_named_catalogue(self):
        from app.search.query_router import _cache_key
        assert _cache_key("laptop", "default") != _cache_key("laptop", "electronics")

    def test_normalisation_still_applies_with_client_id(self):
        from app.search.query_router import _cache_key
        assert _cache_key("Floral Dress", "fashion") == _cache_key("floral dress", "fashion")
        assert _cache_key("  floral dress  ", "fashion") == _cache_key("floral dress", "fashion")

    def test_key_prefix_unchanged(self):
        from app.search.query_router import _cache_key
        assert _cache_key("any query", "fashion").startswith("query_router:")


# ── Config-driven classify_query ──────────────────────────────────────────────

class TestClassifyQueryWithConfig:
    @pytest.mark.asyncio
    async def test_config_path_calls_llm_and_returns_result(self):
        mock_redis = _mock_redis(cached_value=None)
        raw = _llm_response("SEMANTIC")

        with (
            patch("app.search.query_router.get_redis_client", return_value=mock_redis),
            patch("app.search.query_router.call_llm", new_callable=AsyncMock, return_value=raw) as mock_llm,
        ):
            from app.search.query_router import classify_query
            result = await classify_query("show me floral dresses", config=FASHION_CATALOGUE)

        assert result.type == "SEMANTIC"
        mock_llm.assert_called_once()

    @pytest.mark.asyncio
    async def test_config_prompt_uses_routing_examples_not_hardcoded(self):
        """The prompt passed to the LLM must contain fashion examples, not electronics."""
        mock_redis = _mock_redis(cached_value=None)
        captured_prompt = {}

        async def capture_llm(prompt, **kwargs):
            captured_prompt["value"] = prompt
            return _llm_response("SEMANTIC")

        with (
            patch("app.search.query_router.get_redis_client", return_value=mock_redis),
            patch("app.search.query_router.call_llm", side_effect=capture_llm),
        ):
            from app.search.query_router import classify_query
            await classify_query("floral dress", config=FASHION_CATALOGUE)

        prompt = captured_prompt["value"]
        # Fashion routing examples must appear
        assert "something cute for brunch" in prompt
        assert "show me floral dresses" in prompt
        # Electronics-specific terms must NOT appear
        assert "gaming laptop" not in prompt
        assert "Dell" not in prompt

    @pytest.mark.asyncio
    async def test_config_takes_precedence_over_history(self):
        """When config is provided, history is ignored — config prompt is used."""
        mock_redis = _mock_redis(cached_value=None)
        captured_prompt = {}

        async def capture_llm(prompt, **kwargs):
            captured_prompt["value"] = prompt
            return _llm_response("HYBRID")

        with (
            patch("app.search.query_router.get_redis_client", return_value=mock_redis),
            patch("app.search.query_router.call_llm", side_effect=capture_llm),
        ):
            from app.search.query_router import classify_query
            result = await classify_query(
                "blue dress under $30",
                history="User asked about red tops earlier.",
                config=FASHION_CATALOGUE,
            )

        # history should not appear in the prompt when config is provided
        assert "User asked about red tops earlier" not in captured_prompt["value"]
        assert result.type == "HYBRID"

    @pytest.mark.asyncio
    async def test_config_path_cache_hit_skips_llm(self):
        cached = QueryRouterOutput(type="ANALYTICAL", reasoning="cached")
        mock_redis = _mock_redis(cached_value=cached.model_dump_json())

        with (
            patch("app.search.query_router.get_redis_client", return_value=mock_redis),
            patch("app.search.query_router.call_llm", new_callable=AsyncMock) as mock_llm,
        ):
            from app.search.query_router import classify_query
            result = await classify_query("what colours do you have", config=FASHION_CATALOGUE)

        mock_llm.assert_not_called()
        assert result.type == "ANALYTICAL"

    @pytest.mark.asyncio
    async def test_config_path_cache_miss_writes_to_cache_with_catalogue_key(self):
        mock_redis = _mock_redis(cached_value=None)
        raw = _llm_response("HYBRID")

        with (
            patch("app.search.query_router.get_redis_client", return_value=mock_redis),
            patch("app.search.query_router.call_llm", new_callable=AsyncMock, return_value=raw),
        ):
            from app.search.query_router import classify_query, _cache_key, ROUTER_CACHE_TTL
            await classify_query("blue dress under $30", config=FASHION_CATALOGUE)

        # setex must have been called with the fashion-scoped cache key
        expected_key = _cache_key("blue dress under $30", "fashion")
        call_args = mock_redis.setex.call_args[0]
        assert call_args[0] == expected_key
        assert call_args[1] == ROUTER_CACHE_TTL

    @pytest.mark.asyncio
    async def test_bad_llm_response_raises_validation_error_on_config_path(self):
        mock_redis = _mock_redis(cached_value=None)
        bad = json.dumps({"type": "FUZZY_MATCH", "reasoning": "hallucination"})

        with (
            patch("app.search.query_router.get_redis_client", return_value=mock_redis),
            patch("app.search.query_router.call_llm", new_callable=AsyncMock, return_value=bad),
        ):
            from app.search.query_router import classify_query
            with pytest.raises(ValidationError):
                await classify_query("floral dress", config=FASHION_CATALOGUE)

    @pytest.mark.asyncio
    async def test_electronics_config_uses_electronics_examples(self):
        mock_redis = _mock_redis(cached_value=None)
        captured_prompt = {}

        async def capture_llm(prompt, **kwargs):
            captured_prompt["value"] = prompt
            return _llm_response("SEMANTIC")

        with (
            patch("app.search.query_router.get_redis_client", return_value=mock_redis),
            patch("app.search.query_router.call_llm", side_effect=capture_llm),
        ):
            from app.search.query_router import classify_query
            await classify_query("gaming laptop", config=ELECTRONICS_CATALOGUE)

        prompt = captured_prompt["value"]
        assert "show me gaming laptops" in prompt
        assert "something cute for brunch" not in prompt

    @pytest.mark.asyncio
    async def test_no_config_falls_back_to_static_prompt(self):
        """Without config, the original QUERY_ROUTER_PROMPT is used (backwards compat)."""
        mock_redis = _mock_redis(cached_value=None)
        captured_prompt = {}

        async def capture_llm(prompt, **kwargs):
            captured_prompt["value"] = prompt
            return _llm_response("SEMANTIC")

        with (
            patch("app.search.query_router.get_redis_client", return_value=mock_redis),
            patch("app.search.query_router.call_llm", side_effect=capture_llm),
        ):
            from app.search.query_router import classify_query
            from app.agent.prompts import QUERY_ROUTER_PROMPT
            await classify_query("gaming laptop")

        # Static prompt is used — check the structure matches QUERY_ROUTER_PROMPT
        prompt = captured_prompt["value"]
        assert "Query: gaming laptop" in prompt


# ── Cross-catalogue isolation (integration-style, no LLM) ────────────────────

class TestCrossatalogueIsolation:
    @pytest.mark.asyncio
    async def test_fashion_and_electronics_do_not_share_cache(self):
        """
        Same query classified as SEMANTIC for fashion, ANALYTICAL for electronics.
        They must use different cache entries — no bleed-through.
        """
        from app.search.query_router import classify_query

        fashion_cached = QueryRouterOutput(type="SEMANTIC", reasoning="fashion hit")
        electronics_cached = QueryRouterOutput(type="ANALYTICAL", reasoning="electronics hit")

        def make_redis_for(catalogue_id: str):
            redis = AsyncMock()

            async def get_side_effect(key):
                # Only return a cached hit if the key contains the right catalogue hash
                from app.search.query_router import _cache_key
                if key == _cache_key("what do you have", catalogue_id):
                    return (fashion_cached if catalogue_id == "fashion" else electronics_cached).model_dump_json()
                return None

            redis.get = AsyncMock(side_effect=get_side_effect)
            redis.setex = AsyncMock()
            return redis

        fashion_redis = make_redis_for("fashion")
        electronics_redis = make_redis_for("electronics")

        with patch("app.search.query_router.get_redis_client", side_effect=[fashion_redis, electronics_redis]):
            fashion_result = await classify_query("what do you have", config=FASHION_CATALOGUE)
            electronics_result = await classify_query("what do you have", config=ELECTRONICS_CATALOGUE)

        assert fashion_result.type == "SEMANTIC"
        assert electronics_result.type == "ANALYTICAL"
