"""
Basic smoke tests for the products endpoints.
All tests use dependency overrides — no real DB, Redis, or Kafka required.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user, require_admin
from app.auth.models import User, UserRole
from app.database import get_db
from app.main import create_app
from app.products.schemas import (
    ProductDetailResponse,
    ProductListResponse,
    ProductResponse,
    ReviewResponse,
)


# ── Shared fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def product_id() -> uuid.UUID:
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def fake_product(product_id: uuid.UUID) -> ProductResponse:
    return ProductResponse(
        id=product_id,
        name="Dell XPS 15",
        brand="Dell",
        category="laptop",
        base_price=Decimal("1299.99"),
        current_price=Decimal("1249.99"),
        specs={"ram_gb": 16, "storage_gb": 512},
        stock_count=10,
        avg_rating=4.3,
        is_active=True,
        created_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
    )


@pytest.fixture
def fake_admin_user() -> User:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.role = UserRole.ADMIN
    user.is_active = True
    return user


@pytest.fixture
def client(fake_admin_user: User) -> TestClient:
    """
    App instance with auth and DB overridden.
    Auth: both get_current_user and require_admin return a fake admin user.
    DB: get_db yields an AsyncMock session (service functions are patched per-test).
    """
    app = create_app()

    async def override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_current_user] = lambda: fake_admin_user
    app.dependency_overrides[require_admin] = lambda: fake_admin_user
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_list_products_returns_200(client: TestClient, fake_product: ProductResponse):
    expected = ProductListResponse(
        items=[fake_product], total=1, page=1, limit=20, pages=1
    )
    with patch("app.products.service.get_products", new_callable=AsyncMock) as mock:
        mock.return_value = expected
        response = client.get("/api/products/")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Dell XPS 15"
    assert body["items"][0]["brand"] == "Dell"


def test_get_product_detail_returns_correct_product(
    client: TestClient, fake_product: ProductResponse, product_id: uuid.UUID
):
    detail = ProductDetailResponse(**fake_product.model_dump(), reviews=[])
    with patch("app.products.service.get_product_by_id", new_callable=AsyncMock) as mock:
        mock.return_value = detail
        response = client.get(f"/api/products/{product_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(product_id)
    assert body["name"] == "Dell XPS 15"
    assert body["reviews"] == []


def test_get_product_detail_returns_404_for_unknown_id(client: TestClient):
    unknown_id = uuid.uuid4()
    with patch("app.products.service.get_product_by_id", new_callable=AsyncMock) as mock:
        mock.return_value = None
        response = client.get(f"/api/products/{unknown_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Product not found"


def test_create_product_works(client: TestClient, fake_product: ProductResponse):
    with patch("app.products.service.create_product", new_callable=AsyncMock) as mock:
        mock.return_value = fake_product
        response = client.post(
            "/api/products/",
            json={
                "name": "Dell XPS 15",
                "brand": "Dell",
                "category": "laptop",
                "base_price": "1299.99",
                "current_price": "1249.99",
                "specs": {"ram_gb": 16},
                "stock_count": 10,
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Dell XPS 15"
    assert float(body["current_price"]) == pytest.approx(1249.99)


def test_update_product_price_works(
    client: TestClient, fake_product: ProductResponse, product_id: uuid.UUID
):
    updated = fake_product.model_copy(update={"current_price": Decimal("1199.99")})
    with patch("app.products.service.update_product_price", new_callable=AsyncMock) as mock:
        mock.return_value = updated
        response = client.patch(
            f"/api/products/{product_id}/price",
            json={"new_price": "1199.99"},
        )

    assert response.status_code == 200
    body = response.json()
    assert float(body["current_price"]) == pytest.approx(1199.99)
    assert body["id"] == str(product_id)
