"""
Search endpoint tests — query routing, semantic path, filters, product.viewed consumer.

Strategy:
  - classify_query is patched at app.search.router for all endpoint tests so no
    Bedrock or Redis calls are made.
  - embed, search, rerank are patched at the same module boundary.
  - Consumer test calls _increment_view directly with a mocked Redis client.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import create_app
from app.schemas.llm import QueryRouterOutput
from app.schemas.search import ProductResult, SearchResponse


# ── Shared fixtures / helpers ─────────────────────────────────────────────────

def _make_result(
    product_id: str,
    name: str,
    brand: str,
    category: str = "laptop",
    current_price: float = 999.99,
    avg_rating: float = 4.2,
    relevance_score: float = 0.85,
    stock_available: bool = True,
) -> ProductResult:
    return ProductResult(
        product_id=product_id,
        name=name,
        brand=brand,
        category=category,
        current_price=current_price,
        avg_rating=avg_rating,
        relevance_score=relevance_score,
        stock_available=stock_available,
    )


def _semantic_routing() -> QueryRouterOutput:
    return QueryRouterOutput(type="SEMANTIC", reasoning="exploratory discovery")


def _analytical_routing() -> QueryRouterOutput:
    return QueryRouterOutput(type="ANALYTICAL", reasoning="needs aggregation")


def _hybrid_routing() -> QueryRouterOutput:
    return QueryRouterOutput(type="HYBRID", reasoning="semantic + structured filter")


_FAKE_VECTOR = [0.1] * 1024

_CANDIDATE_POOL = [
    _make_result("p1", "Dell XPS 15", "Dell", current_price=1249.99, relevance_score=0.91),
    _make_result("p2", "MacBook Pro 14", "Apple", current_price=1999.99, relevance_score=0.88),
    _make_result("p3", "ASUS ProArt Studiobook", "ASUS", current_price=1799.99, relevance_score=0.85),
    _make_result("p4", "Lenovo ThinkPad X1", "Lenovo", current_price=1399.99, relevance_score=0.82),
    _make_result("p5", "HP Spectre x360", "HP", current_price=1299.99, relevance_score=0.79),
]


@pytest.fixture
def client() -> TestClient:
    app = create_app()

    async def _stub_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _stub_db
    return TestClient(app, raise_server_exceptions=True)


# ── Query routing ─────────────────────────────────────────────────────────────

class TestQueryRouting:
    def test_semantic_query_proceeds_to_search(self, client: TestClient):
        with (
            patch("app.search.router.classify_query", return_value=_semantic_routing()),
            patch("app.search.router.embed", return_value=_FAKE_VECTOR),
            patch("app.search.router.search", return_value=_CANDIDATE_POOL[:2]),
            patch("app.search.router.rerank", return_value=_CANDIDATE_POOL[:2]),
        ):
            resp = client.post("/api/search/", json={"query": "laptop for video editing"})

        assert resp.status_code == 200
        assert resp.json()["query_type"] == "SEMANTIC"

    def test_analytical_query_routes_to_nl_to_sql(self, client: TestClient):
        from app.schemas.search import NLToSQLResult
        nl_result = NLToSQLResult(
            natural_language_query="which brand has highest ratings",
            generated_sql="SELECT brand, AVG(avg_rating) FROM products GROUP BY brand LIMIT 50",
            validation_passed=True,
            rows=[{"brand": "Dell", "avg_rating": 4.6}],
            rows_returned=1,
        )
        with (
            patch("app.search.router.classify_query", return_value=_analytical_routing()),
            patch("app.search.router.run_nl_to_sql", new_callable=AsyncMock, return_value=nl_result),
        ):
            resp = client.post("/api/search/", json={"query": "which brand has highest ratings"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["question"] == "which brand has highest ratings"
        assert body["rows_returned"] == 1

    def test_analytical_validation_failure_returns_422(self, client: TestClient):
        from app.schemas.search import NLToSQLResult
        nl_result = NLToSQLResult(
            natural_language_query="bad query",
            generated_sql="DROP TABLE products",
            validation_passed=False,
            rows=[],
            rows_returned=0,
        )
        with (
            patch("app.search.router.classify_query", return_value=_analytical_routing()),
            patch("app.search.router.run_nl_to_sql", new_callable=AsyncMock, return_value=nl_result),
        ):
            resp = client.post("/api/search/", json={"query": "bad query"})

        assert resp.status_code == 422

    def test_hybrid_query_routes_to_hybrid_search(self, client: TestClient):
        with (
            patch("app.search.router.classify_query", return_value=_hybrid_routing()),
            patch(
                "app.search.router.hybrid_search",
                new_callable=AsyncMock,
                return_value=_CANDIDATE_POOL[:3],
            ),
        ):
            resp = client.post(
                "/api/search/", json={"query": "best laptop under 80k with good battery"}
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["query_type"] == "HYBRID"
        assert len(body["results"]) == 3

    def test_hybrid_query_returns_search_response_shape(self, client: TestClient):
        with (
            patch("app.search.router.classify_query", return_value=_hybrid_routing()),
            patch(
                "app.search.router.hybrid_search",
                new_callable=AsyncMock,
                return_value=_CANDIDATE_POOL[:2],
            ),
        ):
            resp = client.post("/api/search/", json={"query": "best Dell laptop under 80k"})

        body = resp.json()
        assert body["query"] == "best Dell laptop under 80k"
        assert body["total"] == 2
        assert "results" in body

    def test_classify_query_is_called_with_the_query_string(self, client: TestClient):
        from unittest.mock import ANY
        from app.search.constraint_extractor import ConstraintOutput
        mock_constraints = ConstraintOutput(
            rewritten_query="portable travel laptop",
            max_price=None, min_price=None,
            hard_filters={}, soft_attrs={},
            detected_currency="USD", occasion=None,
        )
        with (
            patch("app.search.router.extract_constraints", new_callable=AsyncMock, return_value=mock_constraints),
            patch("app.search.router.classify_query", return_value=_semantic_routing()) as mock_classify,
            patch("app.search.router.embed", return_value=_FAKE_VECTOR),
            patch("app.search.router.search", return_value=[]),
        ):
            client.post("/api/search/", json={"query": "portable travel laptop"})

        mock_classify.assert_called_once_with("portable travel laptop", config=ANY)

    def test_embed_not_called_for_analytical_query(self, client: TestClient):
        from app.schemas.search import NLToSQLResult
        nl_result = NLToSQLResult(
            natural_language_query="how many laptops are under 50k",
            generated_sql="SELECT COUNT(*) FROM products WHERE current_price < 50000 LIMIT 50",
            validation_passed=True,
            rows=[{"count": 12}],
            rows_returned=1,
        )
        with (
            patch("app.search.router.classify_query", return_value=_analytical_routing()),
            patch("app.search.router.run_nl_to_sql", new_callable=AsyncMock, return_value=nl_result),
            patch("app.search.router.embed") as mock_embed,
        ):
            client.post("/api/search/", json={"query": "how many laptops are under 50k"})

        mock_embed.assert_not_called()


# ── Semantic search — basic ───────────────────────────────────────────────────

class TestSemanticSearch:
    def test_returns_200_with_results(self, client: TestClient):
        with (
            patch("app.search.router.classify_query", return_value=_semantic_routing()),
            patch("app.search.router.embed", return_value=_FAKE_VECTOR),
            patch("app.search.router.search", return_value=_CANDIDATE_POOL),
            patch("app.search.router.rerank", return_value=_CANDIDATE_POOL[:3]),
        ):
            resp = client.post("/api/search/", json={"query": "laptop for video editing"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "laptop for video editing"
        assert body["query_type"] == "SEMANTIC"
        assert len(body["results"]) == 3
        assert body["total"] == 3

    def test_result_fields_are_present(self, client: TestClient):
        expected = _CANDIDATE_POOL[:1]
        with (
            patch("app.search.router.classify_query", return_value=_semantic_routing()),
            patch("app.search.router.embed", return_value=_FAKE_VECTOR),
            patch("app.search.router.search", return_value=expected),
            patch("app.search.router.rerank", return_value=expected),
        ):
            resp = client.post("/api/search/", json={"query": "gaming laptop"})

        result = resp.json()["results"][0]
        assert result["product_id"] == "p1"
        assert result["name"] == "Dell XPS 15"
        assert result["brand"] == "Dell"
        assert result["current_price"] == pytest.approx(1249.99)
        assert result["relevance_score"] == pytest.approx(0.91)

    def test_empty_qdrant_response_returns_empty_list(self, client: TestClient):
        with (
            patch("app.search.router.classify_query", return_value=_semantic_routing()),
            patch("app.search.router.embed", return_value=_FAKE_VECTOR),
            patch("app.search.router.search", return_value=[]),
            patch("app.search.router.rerank") as mock_rerank,
        ):
            resp = client.post("/api/search/", json={"query": "ultrabook"})

        assert resp.status_code == 200
        assert resp.json()["results"] == []
        assert resp.json()["total"] == 0
        mock_rerank.assert_not_called()

    def test_top_k_limits_reranker_output(self, client: TestClient):
        with (
            patch("app.search.router.classify_query", return_value=_semantic_routing()),
            patch("app.search.router.embed", return_value=_FAKE_VECTOR),
            patch("app.search.router.search", return_value=_CANDIDATE_POOL),
            patch("app.search.router.rerank", return_value=_CANDIDATE_POOL[:2]) as mock_rerank,
        ):
            resp = client.post("/api/search/", json={"query": "laptop", "top_k": 2})

        _, call_kwargs = mock_rerank.call_args
        assert call_kwargs.get("top_k", mock_rerank.call_args[0][2]) == 2
        assert len(resp.json()["results"]) == 2

    def test_query_too_short_returns_422(self, client: TestClient):
        resp = client.post("/api/search/", json={"query": ""})
        assert resp.status_code == 422

    def test_missing_query_returns_422(self, client: TestClient):
        resp = client.post("/api/search/", json={"filters": {}})
        assert resp.status_code == 422

    def test_search_passes_query_to_embed(self, client: TestClient):
        from app.search.constraint_extractor import ConstraintOutput
        mock_constraints = ConstraintOutput(
            rewritten_query="thin and light travel laptop",
            max_price=None, min_price=None,
            hard_filters={}, soft_attrs={},
            detected_currency="USD", occasion=None,
        )
        with (
            patch("app.search.router.extract_constraints", new_callable=AsyncMock, return_value=mock_constraints),
            patch("app.search.router.classify_query", return_value=_semantic_routing()),
            patch("app.search.router.embed", return_value=_FAKE_VECTOR) as mock_embed,
            patch("app.search.router.search", return_value=[]),
        ):
            client.post("/api/search/", json={"query": "thin and light travel laptop"})

        mock_embed.assert_called_once_with("thin and light travel laptop")


# ── Price filter ──────────────────────────────────────────────────────────────

_NULL_CONSTRAINTS = None  # filled in via fixture below


class TestPriceFilter:
    @pytest.fixture(autouse=True)
    def patch_extract_constraints(self):
        from app.search.constraint_extractor import ConstraintOutput
        null = ConstraintOutput(
            rewritten_query="laptop",
            max_price=None, min_price=None,
            hard_filters={}, soft_attrs={},
            detected_currency="USD", occasion=None,
        )
        with patch("app.search.router.extract_constraints", new_callable=AsyncMock, return_value=null):
            yield

    def test_max_price_filter_is_passed_to_qdrant(self, client: TestClient):
        with (
            patch("app.search.router.classify_query", return_value=_semantic_routing()),
            patch("app.search.router.embed", return_value=_FAKE_VECTOR),
            patch("app.search.router.search", return_value=[]) as mock_search,
        ):
            client.post(
                "/api/search/",
                json={"query": "budget laptop", "filters": {"max_price": 800.0}},
            )

        qdrant_filter = mock_search.call_args[0][1]
        assert qdrant_filter is not None

    def test_no_filter_passes_none_to_qdrant(self, client: TestClient):
        with (
            patch("app.search.router.classify_query", return_value=_semantic_routing()),
            patch("app.search.router.embed", return_value=_FAKE_VECTOR),
            patch("app.search.router.search", return_value=[]) as mock_search,
        ):
            client.post("/api/search/", json={"query": "laptop"})

        qdrant_filter = mock_search.call_args[0][1]
        assert qdrant_filter is None

    def test_max_price_filter_reduces_result_set(self, client: TestClient):
        under_1300 = [r for r in _CANDIDATE_POOL if r.current_price <= 1300.0]
        with (
            patch("app.search.router.classify_query", return_value=_semantic_routing()),
            patch("app.search.router.embed", return_value=_FAKE_VECTOR),
            patch("app.search.router.search", return_value=under_1300),
            patch("app.search.router.rerank", return_value=under_1300),
        ):
            resp = client.post(
                "/api/search/",
                json={"query": "laptop", "filters": {"max_price": 1300.0}},
            )

        results = resp.json()["results"]
        assert all(r["current_price"] <= 1300.0 for r in results)
        assert len(results) == len(under_1300)

    def test_brand_filter_is_passed_to_qdrant(self, client: TestClient):
        with (
            patch("app.search.router.classify_query", return_value=_semantic_routing()),
            patch("app.search.router.embed", return_value=_FAKE_VECTOR),
            patch("app.search.router.search", return_value=[]) as mock_search,
        ):
            client.post(
                "/api/search/",
                json={"query": "laptop", "filters": {"brand": "Dell"}},
            )

        qdrant_filter = mock_search.call_args[0][1]
        assert qdrant_filter is not None

    def test_in_stock_only_filter_builds_filter_object(self, client: TestClient):
        with (
            patch("app.search.router.classify_query", return_value=_semantic_routing()),
            patch("app.search.router.embed", return_value=_FAKE_VECTOR),
            patch("app.search.router.search", return_value=[]) as mock_search,
        ):
            client.post(
                "/api/search/",
                json={"query": "laptop", "filters": {"in_stock_only": True}},
            )

        qdrant_filter = mock_search.call_args[0][1]
        assert qdrant_filter is not None

    def test_combined_filters_build_single_filter_object(self, client: TestClient):
        with (
            patch("app.search.router.classify_query", return_value=_semantic_routing()),
            patch("app.search.router.embed", return_value=_FAKE_VECTOR),
            patch("app.search.router.search", return_value=[]) as mock_search,
        ):
            client.post(
                "/api/search/",
                json={
                    "query": "laptop",
                    "filters": {
                        "brand": "Dell",
                        "max_price": 1500.0,
                        "in_stock_only": True,
                    },
                },
            )

        qdrant_filter = mock_search.call_args[0][1]
        assert qdrant_filter is not None
        assert len(qdrant_filter.must) == 3


# ── product.viewed Kafka consumer ─────────────────────────────────────────────

class TestProductViewedConsumer:
    @pytest.mark.asyncio
    async def test_increment_view_calls_incr_and_expire(self):
        from app.search.kafka_consumer import _increment_view

        redis = AsyncMock()
        with patch("app.search.kafka_consumer.get_redis_client", return_value=redis):
            await _increment_view("abc-123")

        redis.incr.assert_awaited_once_with("views:abc-123")
        redis.expire.assert_awaited_once_with("views:abc-123", 86400)

    @pytest.mark.asyncio
    async def test_increment_view_ttl_is_24_hours(self):
        from app.search.kafka_consumer import _increment_view, _VIEWS_TTL

        assert _VIEWS_TTL == 86400

        redis = AsyncMock()
        with patch("app.search.kafka_consumer.get_redis_client", return_value=redis):
            await _increment_view("prod-xyz")

        _, ttl_arg = redis.expire.call_args[0]
        assert ttl_arg == 86400

    @pytest.mark.asyncio
    async def test_different_products_get_different_keys(self):
        from app.search.kafka_consumer import _increment_view

        redis = AsyncMock()
        with patch("app.search.kafka_consumer.get_redis_client", return_value=redis):
            await _increment_view("prod-1")
            await _increment_view("prod-2")

        incr_keys = [call[0][0] for call in redis.incr.call_args_list]
        assert "views:prod-1" in incr_keys
        assert "views:prod-2" in incr_keys
        assert incr_keys[0] != incr_keys[1]

    @pytest.mark.asyncio
    async def test_multiple_views_same_product_each_call_increments(self):
        from app.search.kafka_consumer import _increment_view

        redis = AsyncMock()
        with patch("app.search.kafka_consumer.get_redis_client", return_value=redis):
            await _increment_view("hot-product")
            await _increment_view("hot-product")
            await _increment_view("hot-product")

        assert redis.incr.await_count == 3
        assert redis.expire.await_count == 3
