"""
Workers tests — personalisation scoring and post-purchase outreach scheduling.

Test 1 (personalisation scoring):
  Directly exercises the in-memory _score_product function and the
  _flush_preferences path without Kafka or a real DB/Redis.

Test 2 (delivery endpoint + outreach):
  Tests the admin PUT /orders/{id}/status endpoint and verifies:
    • 200 response with delivered_at timestamp
    • order.delivered Kafka event published via publish_order_delivered
    • handle_order_delivered writes a Redis sorted-set entry with a score
      approximately 3 days from now (within 5 seconds tolerance)
"""

import json
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import workers.personalisation_worker as pw
from app.auth.dependencies import get_current_user, require_admin
from app.auth.models import User, UserRole
from app.database import get_db
from app.main import create_app
from app.orders.models import Order, OrderStatus
from app.orders.schemas import OrderItemSnapshot, OrderResponse
from app.redis_client import get_redis
from workers.post_purchase_worker import handle_order_delivered

# ── Shared test data ───────────────────────────────────────────────────────────

_USER_ID    = uuid.uuid4()
_PRODUCT_ID = uuid.uuid4()
_ORDER_ID   = uuid.uuid4()


def _make_admin() -> User:
    user = MagicMock(spec=User)
    user.id   = _USER_ID
    user.role = UserRole.ADMIN
    return user


def _make_delivered_order() -> Order:
    order = MagicMock(spec=Order)
    order.id          = _ORDER_ID
    order.user_id     = _USER_ID
    order.status      = OrderStatus.DELIVERED
    order.delivered_at = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
    order.items       = [{"product_id": str(_PRODUCT_ID), "name": "Dell XPS 15", "qty": 1}]
    return order


async def _fake_db():
    yield AsyncMock()


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def clear_worker_state():
    """Resets module-level dicts before and after each personalisation test."""
    pw.user_scores.clear()
    pw.event_counts.clear()
    pw.last_flush.clear()
    yield
    pw.user_scores.clear()
    pw.event_counts.clear()
    pw.last_flush.clear()


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    return TestClient(app)


# ── Test 1: personalisation scoring ───────────────────────────────────────────

class TestPersonalisationScoring:
    """Pure unit tests — no DB, Redis, or Kafka."""

    def test_preferred_brand_after_more_views(self, clear_worker_state):
        """
        10 product.viewed events for Dell + 5 for Apple →
        Dell accumulates higher score and lands first after sort.
        """
        user_id       = str(uuid.uuid4())
        dell_product  = {"brand": "Dell",  "category": "Laptop", "current_price": 85000.0}
        apple_product = {"brand": "Apple", "category": "Laptop", "current_price": 120000.0}

        for _ in range(10):
            pw._score_product(user_id, dell_product, pw.WEIGHTS[pw.settings.kafka_topic_product_viewed])
        for _ in range(5):
            pw._score_product(user_id, apple_product, pw.WEIGHTS[pw.settings.kafka_topic_product_viewed])

        scores = pw.user_scores[user_id]
        assert scores["brands"]["Dell"]  == 10, "Dell should accumulate weight 10"
        assert scores["brands"]["Apple"] == 5,  "Apple should accumulate weight 5"

        top_brand = sorted(scores["brands"], key=scores["brands"].get, reverse=True)[0]
        assert top_brand == "Dell"

    async def test_flush_writes_dell_as_preferred_brand(self, clear_worker_state):
        """
        After scoring, _flush_preferences UPSERTs Dell as preferred_brands[0].
        The DB execute is mocked to capture the params without a real PG connection.
        """
        user_id       = str(uuid.uuid4())
        dell_product  = {"brand": "Dell",  "category": "Laptop", "current_price": 85000.0}
        apple_product = {"brand": "Apple", "category": "Laptop", "current_price": 120000.0}

        for _ in range(10):
            pw._score_product(user_id, dell_product, 1)
        for _ in range(5):
            pw._score_product(user_id, apple_product, 1)

        captured: dict = {}

        mock_db = AsyncMock()

        async def _capture_execute(stmt, params=None):
            if params:
                captured.update(params)
            return MagicMock()

        mock_db.execute    = _capture_execute
        mock_db.commit     = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__  = AsyncMock(return_value=False)

        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        with (
            patch("workers.personalisation_worker.AsyncSessionLocal", return_value=mock_db),
            patch("workers.personalisation_worker.get_redis_client", return_value=mock_redis),
        ):
            await pw._flush_preferences(user_id)

        assert "brands" in captured, "UPSERT params should include 'brands'"
        brands = json.loads(captured["brands"])
        assert brands[0] == "Dell",  f"Expected Dell first, got: {brands}"
        assert "Apple" in brands,    "Apple should also appear in top brands"

    def test_order_created_weight_higher_than_viewed(self, clear_worker_state):
        """
        order.created (weight 5) adds more score per event than product.viewed (weight 1).
        One order beats five views for the same brand.
        """
        user_id = str(uuid.uuid4())
        product = {"brand": "Sony", "category": "TV", "current_price": 55000.0}

        pw._score_product(user_id, product, pw.WEIGHTS[pw.settings.kafka_topic_order_created])
        assert pw.user_scores[user_id]["brands"]["Sony"] == 5

        pw._score_product(user_id, product, pw.WEIGHTS[pw.settings.kafka_topic_product_viewed])
        pw._score_product(user_id, product, pw.WEIGHTS[pw.settings.kafka_topic_product_viewed])
        pw._score_product(user_id, product, pw.WEIGHTS[pw.settings.kafka_topic_product_viewed])
        pw._score_product(user_id, product, pw.WEIGHTS[pw.settings.kafka_topic_product_viewed])
        # 1 order (weight 5) = 4 views (4 × 1); total should now be 9
        assert pw.user_scores[user_id]["brands"]["Sony"] == 9

    def test_cart_updated_appends_price_only(self, clear_worker_state):
        """
        cart.updated has no product_id, so it records cart_total as a price-range
        signal only — brands and categories stay empty.
        """
        user_id    = str(uuid.uuid4())
        cart_total = 75000.0

        import asyncio

        async def _run():
            await pw._handle_cart_updated({"user_id": user_id, "cart_total": cart_total})

        asyncio.get_event_loop().run_until_complete(_run())

        scores = pw.user_scores.get(user_id, {})
        assert scores.get("brands")     == {},            "No brand signal from cart.updated"
        assert scores.get("categories") == {},            "No category signal from cart.updated"
        assert cart_total in scores.get("prices", []),   "cart_total should be in prices"


# ── Test 2: delivery endpoint + outreach scheduling ────────────────────────────

class TestDeliverOrderEndpoint:

    def test_deliver_order_returns_200_with_delivered_at(self, client, app):
        """PUT /orders/{id}/status 200 → body includes order_id and delivered_at."""
        delivered_order = _make_delivered_order()
        app.dependency_overrides[require_admin] = lambda: _make_admin()
        app.dependency_overrides[get_db]        = _fake_db

        with (
            patch("app.orders.router.service.deliver_order", return_value=delivered_order),
            patch("app.orders.router.publish_order_delivered", return_value=None),
        ):
            resp = client.put(
                f"/api/orders/{_ORDER_ID}/status",
                json={"status": "delivered"},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["order_id"]    == str(_ORDER_ID)
        assert body["status"]      == OrderStatus.DELIVERED
        assert body["delivered_at"] is not None

    def test_order_delivered_kafka_event_published(self, client, app):
        """
        PUT /orders/{id}/status publishes order.delivered via publish_order_delivered
        with the correct order_id, user_id, and product_ids extracted from order.items.
        """
        delivered_order = _make_delivered_order()
        app.dependency_overrides[require_admin] = lambda: _make_admin()
        app.dependency_overrides[get_db]        = _fake_db

        with (
            patch("app.orders.router.service.deliver_order", return_value=delivered_order),
            patch("app.orders.router.publish_order_delivered", return_value=None) as mock_kafka,
        ):
            client.put(f"/api/orders/{_ORDER_ID}/status", json={"status": "delivered"})

        mock_kafka.assert_called_once_with(
            order_id=str(_ORDER_ID),
            user_id=str(_USER_ID),
            product_ids=[str(_PRODUCT_ID)],
        )

    def test_deliver_order_404_for_unknown_order(self, client, app):
        """PUT /orders/{id}/status → 404 when the order doesn't exist."""
        app.dependency_overrides[require_admin] = lambda: _make_admin()
        app.dependency_overrides[get_db]        = _fake_db

        with (
            patch("app.orders.router.service.deliver_order", side_effect=ValueError("not found")),
            patch("app.orders.router.publish_order_delivered", return_value=None),
        ):
            resp = client.put(
                f"/api/orders/{uuid.uuid4()}/status",
                json={"status": "delivered"},
            )

        assert resp.status_code == 404


# ── Test 3: handle_order_delivered — Redis sorted-set scheduling ────────────

class TestReviewOutreachScheduling:

    async def test_3day_score_within_tolerance(self):
        """
        handle_order_delivered enqueues a sorted-set entry whose score is
        3 days from now, within a 5-second tolerance window.
        """
        mock_redis = AsyncMock()
        mock_redis.zadd = AsyncMock()

        event = {
            "order_id":    str(_ORDER_ID),
            "user_id":     str(_USER_ID),
            "product_ids": [str(_PRODUCT_ID)],
        }

        with patch("workers.post_purchase_worker.get_redis_client", return_value=mock_redis):
            before = time.time()
            await handle_order_delivered(event)
            after  = time.time()

        assert mock_redis.zadd.called, "zadd should have been called"
        calls = mock_redis.zadd.call_args_list

        # First call is the 3-day entry
        key, mapping = calls[0].args
        assert key == "review_outreach_queue"

        payload_json, score = list(mapping.items())[0]
        payload = json.loads(payload_json)
        assert payload["order_id"]   == str(_ORDER_ID)
        assert payload["user_id"]    == str(_USER_ID)
        assert "_demo" not in payload, "First entry should not be the demo entry"

        three_days = 3 * 24 * 3600
        assert before + three_days <= score <= after + three_days + 5, (
            f"Score {score:.0f} not within 5s of 3-day window "
            f"[{before + three_days:.0f}, {after + three_days + 5:.0f}]"
        )

    async def test_demo_entry_fires_within_35_seconds(self):
        """
        handle_order_delivered also enqueues a demo entry with score ≤ now + 35s
        so the review flow is testable without waiting 3 days.
        """
        mock_redis = AsyncMock()
        mock_redis.zadd = AsyncMock()

        event = {
            "order_id":    str(_ORDER_ID),
            "user_id":     str(_USER_ID),
            "product_ids": [str(_PRODUCT_ID)],
        }

        with patch("workers.post_purchase_worker.get_redis_client", return_value=mock_redis):
            before = time.time()
            await handle_order_delivered(event)

        calls = mock_redis.zadd.call_args_list
        assert len(calls) == 2, "Expected two zadd calls (3-day + demo)"

        _, mapping2 = calls[1].args
        demo_payload_json, demo_score = list(mapping2.items())[0]
        demo_payload = json.loads(demo_payload_json)

        assert demo_payload.get("_demo") is True,    "Second entry should be the demo entry"
        assert demo_score <= before + 35,            "Demo entry score should be within 35s"

    async def test_missing_order_id_is_ignored(self):
        """handle_order_delivered silently drops events without order_id or user_id."""
        mock_redis = AsyncMock()
        mock_redis.zadd = AsyncMock()

        with patch("workers.post_purchase_worker.get_redis_client", return_value=mock_redis):
            await handle_order_delivered({"user_id": str(_USER_ID)})  # no order_id
            await handle_order_delivered({"order_id": str(_ORDER_ID)})  # no user_id

        mock_redis.zadd.assert_not_called()
