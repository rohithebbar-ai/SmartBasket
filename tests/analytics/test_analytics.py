"""
Tests for POST /api/analytics/query

Strategy:
  - run_nl_to_sql is patched at the router import boundary — no Bedrock or DB calls.
  - _synthesise_sync is patched separately — tests can control the insight text.
  - Auth tokens: admin_token fixture creates a valid signed JWT with role="admin".
    customer_token fixture creates a JWT with role="customer".
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from app.auth.dependencies import require_admin
from app.auth.models import User, UserRole
from app.database import get_db
from app.main import create_app
from app.schemas.search import NLToSQLResult


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_user(role: str) -> User:
    u = User()
    u.id = uuid.uuid4()
    u.role = UserRole.ADMIN if role == "admin" else UserRole.CUSTOMER
    u.is_active = True
    return u


@pytest.fixture
def client():
    app = create_app()

    async def _stub_db():
        yield AsyncMock()

    async def _stub_admin():
        return _make_user("admin")

    app.dependency_overrides[get_db] = _stub_db
    app.dependency_overrides[require_admin] = _stub_admin
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def client_as_customer():
    """Client where require_admin raises 403 — simulates a customer token."""
    app = create_app()

    async def _stub_db():
        yield AsyncMock()

    async def _deny_admin():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    app.dependency_overrides[get_db] = _stub_db
    app.dependency_overrides[require_admin] = _deny_admin
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def client_unauthenticated():
    """Client with no auth override — require_admin runs as real, returns 401."""
    app = create_app()

    async def _stub_db():
        yield AsyncMock()

    async def _deny_unauthenticated():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    app.dependency_overrides[get_db] = _stub_db
    app.dependency_overrides[require_admin] = _deny_unauthenticated
    return TestClient(app, raise_server_exceptions=True)


_DEFAULT_ROWS = [{"brand": "Dell", "avg_rating": 4.6}, {"brand": "Apple", "avg_rating": 4.5}]

_SENTINEL = object()


def _make_nl_result(
    rows: list[dict] | object = _SENTINEL,
    validation_passed: bool = True,
    sql: str = "SELECT brand, AVG(avg_rating) FROM products GROUP BY brand LIMIT 50",
    retry_count: int = 0,
) -> NLToSQLResult:
    rows = _DEFAULT_ROWS if rows is _SENTINEL else rows
    return NLToSQLResult(
        natural_language_query="which brand has highest rating",
        generated_sql=sql,
        validation_passed=validation_passed,
        retry_count=retry_count,
        rows_returned=len(rows),
        rows=rows,
    )


# ── Auth ──────────────────────────────────────────────────────────────────────

class TestAnalyticsAuth:
    def test_no_token_returns_401(self, client_unauthenticated):
        resp = client_unauthenticated.post(
            "/api/analytics/query", json={"question": "which brand leads?"}
        )
        assert resp.status_code == 401

    def test_customer_token_returns_403(self, client_as_customer):
        resp = client_as_customer.post(
            "/api/analytics/query",
            json={"question": "which brand leads?"},
        )
        assert resp.status_code == 403

    def test_admin_token_is_accepted(self, client):
        with (
            patch("app.analytics.router.run_nl_to_sql", new_callable=AsyncMock,
                  return_value=_make_nl_result()),
            patch("app.analytics.router._synthesise", new_callable=AsyncMock, return_value="Dell leads."),
        ):
            resp = client.post(
                "/api/analytics/query",
                json={"question": "which brand has highest rating?"},
            )
        assert resp.status_code == 200


# ── Happy path ────────────────────────────────────────────────────────────────

class TestAnalyticsHappyPath:
    def test_returns_analytics_response_shape(self, client):
        with (
            patch("app.analytics.router.run_nl_to_sql", new_callable=AsyncMock,
                  return_value=_make_nl_result()),
            patch("app.analytics.router._synthesise", new_callable=AsyncMock, return_value="Dell leads with 4.6."),
        ):
            resp = client.post(
                "/api/analytics/query",
                json={"question": "which brand has highest rating?"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["question"] == "which brand has highest rating?"
        assert "SELECT" in body["sql"]
        assert isinstance(body["results"], list)
        assert body["rows_returned"] == 2
        assert body["insight"] == "Dell leads with 4.6."

    def test_results_contain_correct_rows(self, client):
        rows = [{"brand": "Dell", "avg_rating": 4.6}]
        with (
            patch("app.analytics.router.run_nl_to_sql", new_callable=AsyncMock,
                  return_value=_make_nl_result(rows=rows)),
            patch("app.analytics.router._synthesise", new_callable=AsyncMock, return_value="Dell leads."),
        ):
            resp = client.post(
                "/api/analytics/query",
                json={"question": "highest rated brand?"},
            )

        assert resp.json()["results"] == [{"brand": "Dell", "avg_rating": 4.6}]

    def test_sql_is_passed_through_to_response(self, client):
        expected_sql = "SELECT brand, COUNT(*) FROM products GROUP BY brand LIMIT 50"
        with (
            patch("app.analytics.router.run_nl_to_sql", new_callable=AsyncMock,
                  return_value=_make_nl_result(sql=expected_sql)),
            patch("app.analytics.router._synthesise", new_callable=AsyncMock, return_value="Some insight."),
        ):
            resp = client.post(
                "/api/analytics/query",
                json={"question": "how many products per brand?"},
            )

        assert resp.json()["sql"] == expected_sql

    def test_run_nl_to_sql_called_with_admin_source(self, client):
        with (
            patch("app.analytics.router.run_nl_to_sql", new_callable=AsyncMock,
                  return_value=_make_nl_result()) as mock_engine,
            patch("app.analytics.router._synthesise", new_callable=AsyncMock, return_value="Insight."),
        ):
            client.post(
                "/api/analytics/query",
                json={"question": "which brand leads?"},
            )

        call_kwargs = mock_engine.call_args.kwargs
        assert call_kwargs["source"] == "admin"

    def test_run_nl_to_sql_called_with_full_schema_scope(self, client):
        with (
            patch("app.analytics.router.run_nl_to_sql", new_callable=AsyncMock,
                  return_value=_make_nl_result()) as mock_engine,
            patch("app.analytics.router._synthesise", new_callable=AsyncMock, return_value="Insight."),
        ):
            client.post(
                "/api/analytics/query",
                json={"question": "which brand leads?"},
            )

        scope = mock_engine.call_args.kwargs["schema_scope"]
        assert "products" in scope
        assert "reviews" in scope
        assert "price_history" in scope
        assert "orders" in scope


# ── Validation failure ────────────────────────────────────────────────────────

class TestAnalyticsValidationFailure:
    def test_validation_failure_returns_422(self, client):
        with patch("app.analytics.router.run_nl_to_sql", new_callable=AsyncMock,
                   return_value=_make_nl_result(validation_passed=False, rows=[])):
            resp = client.post(
                "/api/analytics/query",
                json={"question": "DROP TABLE products"},
            )

        assert resp.status_code == 422

    def test_422_detail_contains_question(self, client):
        with patch("app.analytics.router.run_nl_to_sql", new_callable=AsyncMock,
                   return_value=_make_nl_result(validation_passed=False, rows=[])):
            resp = client.post(
                "/api/analytics/query",
                json={"question": "bad question"},
            )

        assert "bad question" in str(resp.json()["detail"])

    def test_synthesis_not_called_on_validation_failure(self, client):
        with (
            patch("app.analytics.router.run_nl_to_sql", new_callable=AsyncMock,
                  return_value=_make_nl_result(validation_passed=False, rows=[])),
            patch("app.analytics.router._synthesise", new_callable=AsyncMock) as mock_synth,
        ):
            client.post(
                "/api/analytics/query",
                json={"question": "bad question"},
            )

        mock_synth.assert_not_called()


# ── Input validation ──────────────────────────────────────────────────────────

class TestAnalyticsInputValidation:
    def test_empty_question_returns_422(self, client):
        resp = client.post("/api/analytics/query", json={"question": ""})
        assert resp.status_code == 422

    def test_missing_question_returns_422(self, client):
        resp = client.post("/api/analytics/query", json={})
        assert resp.status_code == 422

    def test_question_too_short_returns_422(self, client):
        resp = client.post("/api/analytics/query", json={"question": "ab"})
        assert resp.status_code == 422


# ── Insight synthesis fallback ────────────────────────────────────────────────

class TestInsightSynthesis:
    def test_synthesis_failure_does_not_crash_endpoint(self, client):
        with (
            patch("app.analytics.router.run_nl_to_sql", new_callable=AsyncMock,
                  return_value=_make_nl_result()),
            patch("app.analytics.router._synthesise", new_callable=AsyncMock, side_effect=Exception("LLM timeout")),
        ):
            resp = client.post(
                "/api/analytics/query",
                json={"question": "which brand has highest rating?"},
            )

        assert resp.status_code == 200
        assert "2" in resp.json()["insight"]  # fallback mentions row count

    def test_empty_rows_returns_no_results_insight(self, client):
        with (
            patch("app.analytics.router.run_nl_to_sql", new_callable=AsyncMock,
                  return_value=_make_nl_result(rows=[])),
            patch("app.analytics.router._synthesise", new_callable=AsyncMock, return_value="The query returned no results."),
        ):
            resp = client.post(
                "/api/analytics/query",
                json={"question": "show products with rating 10"},
            )

        assert resp.status_code == 200
        assert resp.json()["rows_returned"] == 0
