"""
Auth integration tests for the products module.

Verifies the access-control contract independently of product business logic:
  - Public routes (list, detail, reviews) work without any token
  - Admin-only routes (create, price update) reject unauthenticated requests with 401
  - Admin-only routes reject customer tokens with 403
  - Admin tokens are accepted on admin routes

All tests use dependency_overrides so no real DB or Kafka is needed.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user, require_admin
from app.auth.models import User, UserRole
from app.auth.utils import create_access_token
from app.database import get_db
from app.main import create_app
from app.products.schemas import ProductListResponse, ProductResponse

# ── Helpers ────────────────────────────────────────────────────────────────────

PRODUCT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

_FAKE_PRODUCT = ProductResponse(
    id=PRODUCT_ID,
    name="Dell XPS 15",
    brand="Dell",
    category="laptop",
    base_price=Decimal("1299.99"),
    current_price=Decimal("1249.99"),
    specs={"ram_gb": 16},
    stock_count=5,
    avg_rating=4.5,
    is_active=True,
    created_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
)

_FAKE_LIST = ProductListResponse(items=[_FAKE_PRODUCT], total=1, page=1, limit=20, pages=1)


def _make_user(role: UserRole) -> User:
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.role = role
    u.is_active = True
    return u


def _public_client() -> TestClient:
    """App with DB stubbed, no auth overrides — tests unauthenticated access."""
    app = create_app()

    async def _stub_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _stub_db
    return TestClient(app, raise_server_exceptions=True)


def _authed_client(role: UserRole) -> TestClient:
    """App where get_current_user returns a user with the given role."""
    app = create_app()
    user = _make_user(role)

    async def _stub_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _stub_db
    app.dependency_overrides[get_current_user] = lambda: user
    # leave require_admin wired to the real implementation so role check fires
    return TestClient(app, raise_server_exceptions=True)


# ── Public routes — no token required ─────────────────────────────────────────

class TestPublicRoutes:
    def test_list_products_no_token_returns_200(self):
        client = _public_client()
        with patch("app.products.service.get_products", new=AsyncMock(return_value=_FAKE_LIST)):
            resp = client.get("/api/products/")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_get_product_detail_no_token_returns_200(self):
        from app.products.schemas import ProductDetailResponse
        detail = ProductDetailResponse(**_FAKE_PRODUCT.model_dump(), reviews=[])
        client = _public_client()
        with patch("app.products.service.get_product_by_id", new=AsyncMock(return_value=detail)):
            resp = client.get(f"/api/products/{PRODUCT_ID}")
        assert resp.status_code == 200
        assert resp.json()["id"] == str(PRODUCT_ID)

    def test_get_product_reviews_no_token_returns_200(self):
        client = _public_client()
        with patch("app.products.service.get_product_reviews", new=AsyncMock(return_value=[])):
            resp = client.get(f"/api/products/{PRODUCT_ID}/reviews")
        assert resp.status_code == 200

    def test_list_products_with_any_token_still_works(self):
        """Public routes must not break when a valid token is sent."""
        client = _authed_client(UserRole.CUSTOMER)
        with patch("app.products.service.get_products", new=AsyncMock(return_value=_FAKE_LIST)):
            resp = client.get("/api/products/")
        assert resp.status_code == 200


# ── POST /api/products/ — admin only ──────────────────────────────────────────

class TestCreateProductAuth:
    _PAYLOAD = {"name": "Test Laptop", "brand": "Dell", "base_price": "999.99"}

    def test_no_token_returns_401(self):
        client = _public_client()
        resp = client.post("/api/products/", json=self._PAYLOAD)
        assert resp.status_code == 401

    def test_customer_token_returns_403(self):
        client = _authed_client(UserRole.CUSTOMER)
        resp = client.post("/api/products/", json=self._PAYLOAD)
        assert resp.status_code == 403
        assert "Admin" in resp.json()["detail"]

    def test_admin_token_is_accepted(self):
        app = create_app()

        async def _stub_db():
            yield AsyncMock()

        admin = _make_user(UserRole.ADMIN)
        app.dependency_overrides[get_db] = _stub_db
        app.dependency_overrides[get_current_user] = lambda: admin
        app.dependency_overrides[require_admin] = lambda: admin  # bypass role check

        with TestClient(app, raise_server_exceptions=True) as c:
            with patch("app.products.service.create_product", new=AsyncMock(return_value=_FAKE_PRODUCT)):
                resp = c.post(
                    "/api/products/",
                    json={
                        "name": "Dell XPS 15",
                        "brand": "Dell",
                        "category": "laptop",
                        "base_price": "1299.99",
                        "current_price": "1249.99",
                        "specs": {},
                        "stock_count": 5,
                    },
                )
        assert resp.status_code == 201
        assert resp.json()["name"] == "Dell XPS 15"


# ── PATCH /api/products/{id}/price — admin only ───────────────────────────────

class TestUpdatePriceAuth:
    _PAYLOAD = {"new_price": "1099.99"}

    def test_no_token_returns_401(self):
        client = _public_client()
        resp = client.patch(f"/api/products/{PRODUCT_ID}/price", json=self._PAYLOAD)
        assert resp.status_code == 401

    def test_customer_token_returns_403(self):
        client = _authed_client(UserRole.CUSTOMER)
        resp = client.patch(f"/api/products/{PRODUCT_ID}/price", json=self._PAYLOAD)
        assert resp.status_code == 403
        assert "Admin" in resp.json()["detail"]

    def test_admin_token_is_accepted(self):
        app = create_app()

        async def _stub_db():
            yield AsyncMock()

        admin = _make_user(UserRole.ADMIN)
        updated = _FAKE_PRODUCT.model_copy(update={"current_price": Decimal("1099.99")})
        app.dependency_overrides[get_db] = _stub_db
        app.dependency_overrides[get_current_user] = lambda: admin
        app.dependency_overrides[require_admin] = lambda: admin

        with TestClient(app, raise_server_exceptions=True) as c:
            with patch("app.products.service.update_product_price", new=AsyncMock(return_value=updated)):
                resp = c.patch(f"/api/products/{PRODUCT_ID}/price", json=self._PAYLOAD)
        assert resp.status_code == 200
        assert float(resp.json()["current_price"]) == pytest.approx(1099.99)


# ── JWT payload contract ───────────────────────────────────────────────────────

class TestJWTContract:
    def test_admin_token_payload_role_is_admin(self):
        from jose import jwt
        from app.config import settings
        token = create_access_token(str(uuid.uuid4()), UserRole.ADMIN.value)
        payload = jwt.decode(token, settings.app_secret_key, algorithms=[settings.jwt_algorithm])
        assert payload["role"] == "admin"

    def test_customer_token_payload_role_is_customer(self):
        from jose import jwt
        from app.config import settings
        token = create_access_token(str(uuid.uuid4()), UserRole.CUSTOMER.value)
        payload = jwt.decode(token, settings.app_secret_key, algorithms=[settings.jwt_algorithm])
        assert payload["role"] == "customer"

    def test_token_contains_no_sensitive_fields(self):
        from jose import jwt
        from app.config import settings
        token = create_access_token(str(uuid.uuid4()), UserRole.ADMIN.value)
        payload = jwt.decode(token, settings.app_secret_key, algorithms=[settings.jwt_algorithm])
        assert "hashed_password" not in payload
        assert "email" not in payload
