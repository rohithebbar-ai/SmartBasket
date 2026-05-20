"""
Hybrid search tests — RRF merge logic, path isolation, router wiring.

Strategy:
  - _rrf_merge: tested directly as a pure function — no I/O, no mocks.
  - hybrid_search: _sql_ranking and _vector_ranking_sync are patched so no
    Bedrock, Qdrant, or DB calls are made.
  - Router HYBRID path: classify_query and hybrid_search are patched at the
    router import boundary.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import create_app
from app.schemas.llm import QueryRouterOutput
from app.schemas.search import ProductResult
from app.search.hybrid_search import _rrf_merge


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_result(
    product_id: str,
    name: str = "Laptop",
    brand: str = "Dell",
    current_price: float = 1000.0,
    avg_rating: float = 4.0,
    relevance_score: float = 0.8,
) -> ProductResult:
    return ProductResult(
        product_id=product_id,
        name=name,
        brand=brand,
        category="laptop",
        current_price=current_price,
        avg_rating=avg_rating,
        relevance_score=relevance_score,
        stock_available=True,
    )


def _make_sql_row(product_id: str, name: str = "Laptop", brand: str = "Dell") -> dict:
    return {
        "id": product_id,
        "name": name,
        "brand": brand,
        "category": "laptop",
        "current_price": 1000.0,
        "avg_rating": 4.0,
        "stock_count": 10,
    }


def _hybrid_routing() -> QueryRouterOutput:
    return QueryRouterOutput(type="HYBRID", reasoning="semantic + structured filter")


@pytest.fixture
def client() -> TestClient:
    app = create_app()

    async def _stub_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _stub_db
    return TestClient(app, raise_server_exceptions=True)


# ── _rrf_merge unit tests ─────────────────────────────────────────────────────

class TestRrfMerge:
    def test_product_in_both_lists_gets_higher_score(self):
        sql_rows = [_make_sql_row("p1"), _make_sql_row("p2")]
        vector_results = [_make_result("p1"), _make_result("p3")]

        results = _rrf_merge(sql_rows, vector_results, top_k=10)
        pids = [r.product_id for r in results]

        # p1 is in both — should rank first
        assert pids[0] == "p1"

    def test_rrf_score_is_sum_of_both_terms(self):
        # p1 at sql_rank=0, vector_rank=0: score = 1/60 + 1/60 = 2/60
        # p2 at sql_rank=1: score = 1/61
        sql_rows = [_make_sql_row("p1"), _make_sql_row("p2")]
        vector_results = [_make_result("p1")]

        results = _rrf_merge(sql_rows, vector_results, top_k=10)

        p1 = next(r for r in results if r.product_id == "p1")
        p2 = next(r for r in results if r.product_id == "p2")

        expected_p1 = round(1 / 60 + 1 / 60, 6)
        expected_p2 = round(1 / 61, 6)
        assert p1.relevance_score == pytest.approx(expected_p1)
        assert p2.relevance_score == pytest.approx(expected_p2)

    def test_sql_only_product_appears_in_results(self):
        sql_rows = [_make_sql_row("sql-only")]
        vector_results = [_make_result("vector-only")]

        results = _rrf_merge(sql_rows, vector_results, top_k=10)
        pids = {r.product_id for r in results}

        assert "sql-only" in pids
        assert "vector-only" in pids

    def test_vector_only_product_appears_in_results(self):
        sql_rows = []
        vector_results = [_make_result("v1"), _make_result("v2")]

        results = _rrf_merge(sql_rows, vector_results, top_k=10)
        assert len(results) == 2
        assert results[0].product_id == "v1"  # rank 0 in vector

    def test_sql_only_path_returns_results(self):
        sql_rows = [_make_sql_row("s1"), _make_sql_row("s2")]
        vector_results = []

        results = _rrf_merge(sql_rows, vector_results, top_k=10)
        assert len(results) == 2
        assert results[0].product_id == "s1"

    def test_both_empty_returns_empty(self):
        results = _rrf_merge([], [], top_k=10)
        assert results == []

    def test_top_k_limits_output(self):
        sql_rows = [_make_sql_row(f"p{i}") for i in range(20)]
        vector_results = [_make_result(f"p{i}") for i in range(20)]

        results = _rrf_merge(sql_rows, vector_results, top_k=5)
        assert len(results) == 5

    def test_results_sorted_by_rrf_score_descending(self):
        # p1 at sql_rank=0 and vector_rank=0 → highest score
        # p5 at sql_rank=4 and vector_rank=4 → lowest
        sql_rows = [_make_sql_row(f"p{i}") for i in range(5)]
        vector_results = [_make_result(f"p{i}") for i in range(5)]

        results = _rrf_merge(sql_rows, vector_results, top_k=5)

        scores = [r.relevance_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_vector_data_preferred_over_sql_row_for_shared_product(self):
        # When a product is in both lists, the ProductResult should carry
        # the richer Qdrant data (sentiment_scores, use_cases present)
        sql_rows = [_make_sql_row("p1", name="SQL Name")]
        vector_result = _make_result("p1", name="Vector Name")
        vector_result = ProductResult(
            product_id="p1",
            name="Vector Name",
            brand="Dell",
            category="laptop",
            current_price=999.0,
            avg_rating=4.5,
            relevance_score=0.9,
            sentiment_scores={"battery_sentiment": 4.2},
            use_cases=["video_editing"],
        )
        results = _rrf_merge(sql_rows, [vector_result], top_k=10)

        p1 = next(r for r in results if r.product_id == "p1")
        assert p1.name == "Vector Name"
        assert p1.sentiment_scores == {"battery_sentiment": 4.2}
        assert p1.use_cases == ["video_editing"]

    def test_sql_row_with_product_id_key_is_normalised(self):
        # Some SQL queries may return 'product_id' instead of 'id'
        sql_rows = [{"product_id": "norm-1", "id": "norm-1", "name": "X",
                     "brand": "B", "category": "c", "current_price": 100,
                     "avg_rating": 3.5, "stock_count": 5}]
        results = _rrf_merge(sql_rows, [], top_k=10)
        assert len(results) == 1
        assert results[0].product_id == "norm-1"


# ── hybrid_search function tests ──────────────────────────────────────────────

class TestHybridSearchFunction:
    @pytest.mark.asyncio
    async def test_both_paths_called_concurrently(self):
        from app.search.hybrid_search import hybrid_search

        sql_rows = [_make_sql_row("p1"), _make_sql_row("p2")]
        vector_results = [_make_result("p1"), _make_result("p3")]

        mock_db = AsyncMock()
        with (
            patch("app.search.hybrid_search._sql_ranking", new_callable=AsyncMock,
                  return_value=sql_rows) as mock_sql,
            patch("app.search.hybrid_search._vector_ranking_sync",
                  return_value=vector_results) as mock_vec,
        ):
            results = await hybrid_search("best Dell laptop under 80k", mock_db, top_k=10)

        mock_sql.assert_awaited_once()
        mock_vec.assert_called_once()
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_sql_path_failure_falls_back_to_vector_only(self):
        from app.search.hybrid_search import hybrid_search

        vector_results = [_make_result("v1"), _make_result("v2")]

        mock_db = AsyncMock()
        with (
            patch("app.search.hybrid_search._sql_ranking", new_callable=AsyncMock,
                  return_value=[]),
            patch("app.search.hybrid_search._vector_ranking_sync",
                  return_value=vector_results),
        ):
            results = await hybrid_search("best laptop with good battery", mock_db)

        assert len(results) == 2
        pids = {r.product_id for r in results}
        assert "v1" in pids
        assert "v2" in pids

    @pytest.mark.asyncio
    async def test_vector_path_failure_falls_back_to_sql_only(self):
        from app.search.hybrid_search import hybrid_search

        sql_rows = [_make_sql_row("s1"), _make_sql_row("s2")]

        mock_db = AsyncMock()
        with (
            patch("app.search.hybrid_search._sql_ranking", new_callable=AsyncMock,
                  return_value=sql_rows),
            patch("app.search.hybrid_search._vector_ranking_sync", return_value=[]),
        ):
            results = await hybrid_search("best laptop under 80k", mock_db)

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_both_paths_empty_returns_empty_list(self):
        from app.search.hybrid_search import hybrid_search

        mock_db = AsyncMock()
        with (
            patch("app.search.hybrid_search._sql_ranking", new_callable=AsyncMock,
                  return_value=[]),
            patch("app.search.hybrid_search._vector_ranking_sync", return_value=[]),
        ):
            results = await hybrid_search("obscure query", mock_db)

        assert results == []

    @pytest.mark.asyncio
    async def test_top_k_passed_to_rrf_merge(self):
        from app.search.hybrid_search import hybrid_search

        sql_rows = [_make_sql_row(f"p{i}") for i in range(20)]
        vector_results = [_make_result(f"p{i}") for i in range(20)]

        mock_db = AsyncMock()
        with (
            patch("app.search.hybrid_search._sql_ranking", new_callable=AsyncMock,
                  return_value=sql_rows),
            patch("app.search.hybrid_search._vector_ranking_sync",
                  return_value=vector_results),
        ):
            results = await hybrid_search("laptop", mock_db, top_k=5)

        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_product_in_both_paths_ranked_first(self):
        from app.search.hybrid_search import hybrid_search

        # p1 in both → highest RRF score → first result
        sql_rows = [_make_sql_row("p1"), _make_sql_row("p2")]
        vector_results = [_make_result("p1"), _make_result("p3")]

        mock_db = AsyncMock()
        with (
            patch("app.search.hybrid_search._sql_ranking", new_callable=AsyncMock,
                  return_value=sql_rows),
            patch("app.search.hybrid_search._vector_ranking_sync",
                  return_value=vector_results),
        ):
            results = await hybrid_search("best Dell laptop under 80k", mock_db, top_k=10)

        assert results[0].product_id == "p1"


# ── Router HYBRID path tests ──────────────────────────────────────────────────

class TestRouterHybridPath:
    def test_hybrid_returns_200(self, client: TestClient):
        candidates = [_make_result(f"p{i}") for i in range(3)]
        with (
            patch("app.search.router.classify_query", return_value=_hybrid_routing()),
            patch("app.search.router.hybrid_search", new_callable=AsyncMock,
                  return_value=candidates),
        ):
            resp = client.post(
                "/api/search/", json={"query": "best laptop under 80k with good battery"}
            )

        assert resp.status_code == 200

    def test_hybrid_response_has_correct_query_type(self, client: TestClient):
        with (
            patch("app.search.router.classify_query", return_value=_hybrid_routing()),
            patch("app.search.router.hybrid_search", new_callable=AsyncMock,
                  return_value=[]),
        ):
            resp = client.post("/api/search/", json={"query": "best Dell laptop under 80k"})

        assert resp.json()["query_type"] == "HYBRID"

    def test_hybrid_response_shape(self, client: TestClient):
        candidates = [_make_result("p1", relevance_score=0.032)]
        with (
            patch("app.search.router.classify_query", return_value=_hybrid_routing()),
            patch("app.search.router.hybrid_search", new_callable=AsyncMock,
                  return_value=candidates),
        ):
            resp = client.post(
                "/api/search/", json={"query": "top rated Dell laptop under 80k"}
            )

        body = resp.json()
        assert body["query"] == "top rated Dell laptop under 80k"
        assert body["total"] == 1
        assert body["results"][0]["product_id"] == "p1"

    def test_hybrid_passes_top_k_to_hybrid_search(self, client: TestClient):
        with (
            patch("app.search.router.classify_query", return_value=_hybrid_routing()),
            patch("app.search.router.hybrid_search", new_callable=AsyncMock,
                  return_value=[]) as mock_hs,
        ):
            client.post("/api/search/", json={"query": "best laptop", "top_k": 7})

        call_kwargs = mock_hs.call_args.kwargs
        assert call_kwargs["top_k"] == 7

    def test_hybrid_empty_results_returns_200_with_empty_list(self, client: TestClient):
        with (
            patch("app.search.router.classify_query", return_value=_hybrid_routing()),
            patch("app.search.router.hybrid_search", new_callable=AsyncMock,
                  return_value=[]),
        ):
            resp = client.post("/api/search/", json={"query": "impossible hybrid query"})

        assert resp.status_code == 200
        assert resp.json()["results"] == []
        assert resp.json()["total"] == 0

    def test_embed_not_called_for_hybrid_query(self, client: TestClient):
        with (
            patch("app.search.router.classify_query", return_value=_hybrid_routing()),
            patch("app.search.router.hybrid_search", new_callable=AsyncMock,
                  return_value=[]),
            patch("app.search.router.embed") as mock_embed,
        ):
            client.post("/api/search/", json={"query": "best Dell laptop under 80k"})

        mock_embed.assert_not_called()
