"""
Orders module tests — cart add/remove, order creation, price.updated consumer.

Strategy: patch service functions and Kafka publishers at the router boundary.
This keeps tests fast (no Redis/DB/Kafka) and focused on HTTP contracts.
The consumer test calls _recalculate_carts directly with a mocked Redis client.
"""

import json
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.models import User, UserRole
from app.database import get_db
from app.main import create_app
from app.orders.schemas import CartItem, CartResponse, OrderItemSnapshot, OrderResponse
from app.orders.models import OrderStatus
from app.redis_client import get_redis

# ── Shared test data ──────────────────────────────────────────────────────────

USER_ID    = uuid.uuid4()
PRODUCT_ID = uuid.uuid4()
ORDER_ID   = uuid.uuid4()
UNIT_PRICE = Decimal("999.99")


def _make_user(role: UserRole = UserRole.CUSTOMER) -> User:
    user = MagicMock(spec=User)
    user.id   = USER_ID
    user.role = role
    return user


def _cart_response(qty: int = 1) -> CartResponse:
    item = CartItem(product_id=PRODUCT_ID, name="Dell XPS 15", qty=qty, unit_price=UNIT_PRICE)
    return CartResponse(user_id=USER_ID, items=[item], total=UNIT_PRICE * qty)


def _empty_cart() -> CartResponse:
    return CartResponse(user_id=USER_ID, items=[], total=Decimal("0"))


def _order_response() -> OrderResponse:
    snapshot = OrderItemSnapshot(
        product_id=PRODUCT_ID,
        name="Dell XPS 15",
        price_at_order=UNIT_PRICE,
        qty=1,
    )
    return OrderResponse(
        id=ORDER_ID,
        user_id=USER_ID,
        items=[snapshot],
        total_amount=UNIT_PRICE,
        status=OrderStatus.PENDING,
        created_at=__import__("datetime").datetime.utcnow(),
    )


# ── App factory with dependency overrides ─────────────────────────────────────

def _make_client(user: User | None = None) -> TestClient:
    """Returns a TestClient with auth, DB, and Redis dependencies overridden."""
    app = create_app()
    _user = user or _make_user()

    async def _mock_redis():
        yield AsyncMock()

    async def _mock_db():
        yield AsyncMock()

    app.dependency_overrides[get_current_user] = lambda: _user
    app.dependency_overrides[get_redis]        = _mock_redis
    app.dependency_overrides[get_db]           = _mock_db
    return TestClient(app, raise_server_exceptions=True)


# ── Cart: add ─────────────────────────────────────────────────────────────────

class TestAddToCart:
    def test_returns_cart_with_item(self):
        client = _make_client()
        with (
            patch("app.orders.router.service.add_to_cart", new=AsyncMock(return_value=_cart_response())),
            patch("app.orders.router.publish_cart_updated", new=AsyncMock()),
        ):
            resp = client.post("/api/orders/cart/add", json={"product_id": str(PRODUCT_ID), "qty": 1})

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["product_id"] == str(PRODUCT_ID)
        assert float(body["total"]) == float(UNIT_PRICE)

    def test_publishes_cart_updated_event(self):
        client = _make_client()
        mock_publish = AsyncMock()
        with (
            patch("app.orders.router.service.add_to_cart", new=AsyncMock(return_value=_cart_response())),
            patch("app.orders.router.publish_cart_updated", new=mock_publish),
        ):
            client.post("/api/orders/cart/add", json={"product_id": str(PRODUCT_ID), "qty": 1})

        mock_publish.assert_called_once()
        # publish_cart_updated is called with positional args (user_id, total)
        assert mock_publish.call_args.args[0] == USER_ID

    def test_product_not_found_returns_404(self):
        client = _make_client()
        with (
            patch("app.orders.router.service.add_to_cart", new=AsyncMock(side_effect=ValueError("Product not found"))),
            patch("app.orders.router.publish_cart_updated", new=AsyncMock()),
        ):
            resp = client.post("/api/orders/cart/add", json={"product_id": str(PRODUCT_ID), "qty": 1})

        assert resp.status_code == 404

    def test_invalid_qty_returns_422(self):
        client = _make_client()
        resp = client.post("/api/orders/cart/add", json={"product_id": str(PRODUCT_ID), "qty": 0})
        assert resp.status_code == 422  # Pydantic ge=1 validation


# ── Cart: remove ──────────────────────────────────────────────────────────────

class TestRemoveFromCart:
    def test_returns_updated_cart(self):
        client = _make_client()
        with (
            patch("app.orders.router.service.remove_from_cart", new=AsyncMock(return_value=_empty_cart())),
            patch("app.orders.router.publish_cart_updated", new=AsyncMock()),
        ):
            resp = client.delete(f"/api/orders/cart/remove?product_id={PRODUCT_ID}")

        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_publishes_cart_updated_after_remove(self):
        client = _make_client()
        mock_publish = AsyncMock()
        with (
            patch("app.orders.router.service.remove_from_cart", new=AsyncMock(return_value=_empty_cart())),
            patch("app.orders.router.publish_cart_updated", new=mock_publish),
        ):
            client.delete(f"/api/orders/cart/remove?product_id={PRODUCT_ID}")

        mock_publish.assert_called_once()


# ── Cart: get ─────────────────────────────────────────────────────────────────

class TestGetCart:
    def test_own_cart_accessible(self):
        client = _make_client()
        with patch("app.orders.router.service.get_cart", new=AsyncMock(return_value=_cart_response())):
            resp = client.get(f"/api/orders/cart/{USER_ID}")

        assert resp.status_code == 200
        assert resp.json()["user_id"] == str(USER_ID)

    def test_other_users_cart_returns_403(self):
        other_id = uuid.uuid4()
        client   = _make_client()  # logged in as USER_ID
        with patch("app.orders.router.service.get_cart", new=AsyncMock(return_value=_cart_response())):
            resp = client.get(f"/api/orders/cart/{other_id}")

        assert resp.status_code == 403

    def test_admin_can_access_any_cart(self):
        admin  = _make_user(role=UserRole.ADMIN)
        client = _make_client(user=admin)
        other_id = uuid.uuid4()
        with patch("app.orders.router.service.get_cart", new=AsyncMock(return_value=_cart_response())):
            resp = client.get(f"/api/orders/cart/{other_id}")

        assert resp.status_code == 200


# ── Orders: create ────────────────────────────────────────────────────────────

class TestCreateOrder:
    def test_creates_order_from_cart(self):
        client = _make_client()
        with (
            patch("app.orders.router.service.create_order", new=AsyncMock(return_value=_order_response())),
            patch("app.orders.router.publish_order_created", new=AsyncMock()),
        ):
            resp = client.post("/api/orders")

        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "pending"
        assert len(body["items"]) == 1
        assert float(body["total_amount"]) == float(UNIT_PRICE)

    def test_publishes_order_created_event(self):
        client = _make_client()
        mock_publish = AsyncMock()
        with (
            patch("app.orders.router.service.create_order", new=AsyncMock(return_value=_order_response())),
            patch("app.orders.router.publish_order_created", new=mock_publish),
        ):
            client.post("/api/orders")

        mock_publish.assert_called_once()
        call_kwargs = mock_publish.call_args.kwargs
        assert "order_id" in call_kwargs or mock_publish.call_args.args

    def test_empty_cart_returns_400(self):
        client = _make_client()
        with (
            patch("app.orders.router.service.create_order", new=AsyncMock(side_effect=ValueError("Cannot create order from an empty cart"))),
            patch("app.orders.router.publish_order_created", new=AsyncMock()),
        ):
            resp = client.post("/api/orders")

        assert resp.status_code == 400
        assert "empty cart" in resp.json()["detail"]

    def test_order_not_published_on_service_error(self):
        client = _make_client()
        mock_publish = AsyncMock()
        with (
            patch("app.orders.router.service.create_order", new=AsyncMock(side_effect=ValueError("empty cart"))),
            patch("app.orders.router.publish_order_created", new=mock_publish),
        ):
            client.post("/api/orders")

        mock_publish.assert_not_called()


# ── Orders: get ───────────────────────────────────────────────────────────────

class TestGetOrder:
    def test_returns_order_for_owner(self):
        client = _make_client()
        with patch("app.orders.router.service.get_order_by_id", new=AsyncMock(return_value=_order_response())):
            resp = client.get(f"/api/orders/{ORDER_ID}")

        assert resp.status_code == 200
        assert resp.json()["id"] == str(ORDER_ID)

    def test_order_not_found_returns_404(self):
        client = _make_client()
        with patch("app.orders.router.service.get_order_by_id", new=AsyncMock(return_value=None)):
            resp = client.get(f"/api/orders/{ORDER_ID}")

        assert resp.status_code == 404


# ── Consumer: price.updated recalculates cart ─────────────────────────────────

class TestPriceUpdatedConsumer:
    @pytest.mark.asyncio
    async def test_recalculates_cart_item_price(self):
        from app.orders.kafka_consumer import _recalculate_carts

        old_item = CartItem(
            product_id=PRODUCT_ID,
            name="Dell XPS 15",
            qty=2,
            unit_price=Decimal("999.99"),
        )
        new_price = Decimal("1099.99")

        # Mock Redis scan_iter yielding one cart key, hget returning the old item
        mock_redis = AsyncMock()
        mock_redis.scan_iter = MagicMock(
            return_value=_async_iter([f"cart:{USER_ID}"])
        )
        mock_redis.hget = AsyncMock(return_value=old_item.model_dump_json())
        mock_redis.hset = AsyncMock()

        with patch("app.orders.kafka_consumer.get_redis_client", return_value=mock_redis):
            await _recalculate_carts(str(PRODUCT_ID), new_price)

        # hset must be called with the updated price
        mock_redis.hset.assert_called_once()
        _, call_args, _ = mock_redis.hset.mock_calls[0]
        written = json.loads(call_args[2])
        assert Decimal(written["unit_price"]) == new_price

    @pytest.mark.asyncio
    async def test_skips_carts_without_the_product(self):
        from app.orders.kafka_consumer import _recalculate_carts

        mock_redis = AsyncMock()
        mock_redis.scan_iter = MagicMock(return_value=_async_iter([f"cart:{USER_ID}"]))
        mock_redis.hget      = AsyncMock(return_value=None)  # product not in this cart
        mock_redis.hset      = AsyncMock()

        with patch("app.orders.kafka_consumer.get_redis_client", return_value=mock_redis):
            await _recalculate_carts(str(PRODUCT_ID), Decimal("1099.99"))

        mock_redis.hset.assert_not_called()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _async_iter(items):
    """Yields items as an async generator — simulates Redis scan_iter."""
    for item in items:
        yield item
