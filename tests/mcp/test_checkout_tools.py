"""
MCP checkout tools tests — cart, payment, and notification tool endpoints.

Strategy: patch service functions and DB/Redis clients at the module boundary
so tests are fast (no live PostgreSQL/Redis/Stripe). All tools are exercised via
the FastAPI TestClient against their HTTP endpoints at /mcp/tools/{tool_name}.

Coverage:
  check_stock_status            — in-stock, out-of-stock, unknown product → 404
  add_to_cart                   — success shape; service called with correct IDs
  calculate_order_total         — GST applied; delivery fee thresholds (< 50k / ≥ 50k)
  process_payment               — dev-mode mock order; create_order called; empty cart → 400
  send_confirmation_email       — skips gracefully when SendGrid not configured
  set_price_alert               — stores alert and returns alert_set=True
  list_tools                    — all 10 tools present; read/write classification correct
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.orders.schemas import CartItem, CartResponse

# ── Shared test data ──────────────────────────────────────────────────────────

USER_ID    = uuid.uuid4()
PRODUCT_ID = uuid.uuid4()
ORDER_ID   = uuid.uuid4()


def _cart(unit_price: Decimal = Decimal("78750")) -> CartResponse:
    item = CartItem(product_id=PRODUCT_ID, name="Dell XPS 15", qty=1, unit_price=unit_price)
    return CartResponse(user_id=USER_ID, items=[item], total=unit_price)


def _empty_cart() -> CartResponse:
    return CartResponse(user_id=USER_ID, items=[], total=Decimal("0"))


def _order_mock() -> MagicMock:
    order              = MagicMock()
    order.id           = ORDER_ID
    order.total_amount = Decimal("94158.50")
    order.items        = []
    return order


def _db_session(first_row=None, all_rows=None) -> AsyncMock:
    """
    Returns an async context-manager mock for AsyncSessionLocal.
    Configures .execute() → .mappings() → .first() / .all() with the given rows.
    """
    session                  = AsyncMock()
    session.__aenter__       = AsyncMock(return_value=session)
    session.__aexit__        = AsyncMock(return_value=False)
    session.commit           = AsyncMock()

    mappings                 = MagicMock()
    mappings.first.return_value = first_row
    mappings.all.return_value   = all_rows or ([first_row] if first_row else [])

    execute_result           = MagicMock()
    execute_result.mappings.return_value = mappings
    session.execute          = AsyncMock(return_value=execute_result)
    return session


def _make_client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=True)


# ── Test 1: check_stock_status ────────────────────────────────────────────────

class TestCheckStockStatus:
    def test_in_stock_product_returns_correct_shape(self):
        client = _make_client()
        db_row = {
            "name": "XPS 15", "brand": "Dell",
            "current_price": 78750.0, "stock_count": 25,
        }
        with patch("app.mcp.tools.cart_tools.AsyncSessionLocal", return_value=_db_session(first_row=db_row)):
            resp = client.post("/mcp/tools/check_stock_status", json={"product_id": str(PRODUCT_ID)})

        assert resp.status_code == 200
        body = resp.json()
        assert body["in_stock"] is True
        assert body["stock_count"] > 0
        assert body["current_price"] == 78750.0
        assert "Dell" in body["product_name"]

    def test_zero_stock_returns_in_stock_false(self):
        client = _make_client()
        db_row = {
            "name": "XPS 15", "brand": "Dell",
            "current_price": 78750.0, "stock_count": 0,
        }
        with patch("app.mcp.tools.cart_tools.AsyncSessionLocal", return_value=_db_session(first_row=db_row)):
            resp = client.post("/mcp/tools/check_stock_status", json={"product_id": str(PRODUCT_ID)})

        assert resp.status_code == 200
        body = resp.json()
        assert body["in_stock"] is False
        assert body["stock_count"] == 0

    def test_unknown_product_returns_404(self):
        client = _make_client()
        with patch("app.mcp.tools.cart_tools.AsyncSessionLocal", return_value=_db_session(first_row=None)):
            resp = client.post(
                "/mcp/tools/check_stock_status",
                json={"product_id": str(uuid.uuid4())},
            )

        assert resp.status_code == 404


# ── Test 2: add_to_cart ───────────────────────────────────────────────────────

class TestAddToCart:
    def test_returns_success_and_positive_cart_total(self):
        client = _make_client()
        with (
            patch("app.mcp.tools.cart_tools.get_redis_client", new=AsyncMock(return_value=AsyncMock())),
            patch("app.mcp.tools.cart_tools.AsyncSessionLocal", return_value=_db_session()),
            patch("app.orders.service.add_to_cart", new=AsyncMock(return_value=_cart())),
        ):
            resp = client.post("/mcp/tools/add_to_cart", json={
                "user_id": str(USER_ID), "product_id": str(PRODUCT_ID), "quantity": 1,
            })

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["cart_total"] > 0

    def test_service_called_with_correct_user_and_product_ids(self):
        """
        Verifies the Redis cart write (via order_service.add_to_cart) is called with
        the right user_id and product_id — i.e. the cart key cart:{user_id} will hold
        the correct product after this call.
        """
        client   = _make_client()
        mock_add = AsyncMock(return_value=_cart())
        with (
            patch("app.mcp.tools.cart_tools.get_redis_client", new=AsyncMock(return_value=AsyncMock())),
            patch("app.mcp.tools.cart_tools.AsyncSessionLocal", return_value=_db_session()),
            patch("app.orders.service.add_to_cart", new=mock_add),
        ):
            client.post("/mcp/tools/add_to_cart", json={
                "user_id": str(USER_ID), "product_id": str(PRODUCT_ID), "quantity": 1,
            })

        mock_add.assert_called_once()
        kwargs = mock_add.call_args.kwargs
        assert kwargs["user_id"]    == USER_ID
        assert kwargs["product_id"] == PRODUCT_ID
        assert kwargs["qty"]        == 1

    def test_item_added_name_in_response(self):
        client = _make_client()
        with (
            patch("app.mcp.tools.cart_tools.get_redis_client", new=AsyncMock(return_value=AsyncMock())),
            patch("app.mcp.tools.cart_tools.AsyncSessionLocal", return_value=_db_session()),
            patch("app.orders.service.add_to_cart", new=AsyncMock(return_value=_cart())),
        ):
            resp = client.post("/mcp/tools/add_to_cart", json={
                "user_id": str(USER_ID), "product_id": str(PRODUCT_ID), "quantity": 1,
            })

        assert "Dell XPS 15" in resp.json()["item_added"]


# ── Test 3: calculate_order_total ─────────────────────────────────────────────

class TestCalculateOrderTotal:
    def _call(self, unit_price: Decimal) -> dict:
        client = _make_client()
        with (
            patch("app.mcp.tools.payment_tools.get_redis_client", new=AsyncMock(return_value=AsyncMock())),
            patch("app.orders.service.get_cart", new=AsyncMock(return_value=_cart(unit_price))),
        ):
            resp = client.post(
                "/mcp/tools/calculate_order_total",
                json={"user_id": str(USER_ID)},
            )
        assert resp.status_code == 200
        return resp.json()

    def test_total_exceeds_subtotal_because_gst_is_applied(self):
        body = self._call(Decimal("78750"))
        assert body["total"] > body["subtotal"]
        # GST = subtotal * 0.18
        assert abs(body["gst"] - body["subtotal"] * 0.18) < 0.01

    def test_delivery_fee_99_when_subtotal_below_50k(self):
        body = self._call(Decimal("20000"))
        assert body["delivery_fee"] == 99.0

    def test_free_delivery_when_subtotal_exactly_50k(self):
        body = self._call(Decimal("50000"))
        assert body["delivery_fee"] == 0.0

    def test_free_delivery_when_subtotal_above_50k(self):
        body = self._call(Decimal("78750"))
        assert body["delivery_fee"] == 0.0

    def test_empty_cart_returns_400(self):
        client = _make_client()
        with (
            patch("app.mcp.tools.payment_tools.get_redis_client", new=AsyncMock(return_value=AsyncMock())),
            patch("app.orders.service.get_cart", new=AsyncMock(return_value=_empty_cart())),
        ):
            resp = client.post(
                "/mcp/tools/calculate_order_total",
                json={"user_id": str(USER_ID)},
            )

        assert resp.status_code == 400
        assert "empty" in resp.json()["detail"].lower()


# ── Test 4: process_payment ───────────────────────────────────────────────────

class TestProcessPayment:
    """
    Tests run against the dev-mode (no-Stripe) path because STRIPE_SECRET_KEY
    is not set in the test environment. The tool detects the missing key and
    creates a mock order directly, which is the correct dev behaviour.
    """

    def test_returns_success_with_valid_uuid_order_id(self):
        client = _make_client()
        order  = _order_mock()
        with (
            patch("app.mcp.tools.payment_tools.get_redis_client", new=AsyncMock(return_value=AsyncMock())),
            patch("app.orders.service.get_cart",    new=AsyncMock(return_value=_cart())),
            patch("app.orders.service.create_order", new=AsyncMock(return_value=order)),
            patch("app.mcp.tools.payment_tools.AsyncSessionLocal", return_value=_db_session()),
        ):
            resp = client.post("/mcp/tools/process_payment", json={
                "user_id": str(USER_ID), "payment_method_id": "pm_card_visa",
            })

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert uuid.UUID(body["order_id"])  # raises if not a valid UUID

    def test_create_order_called_once_with_correct_user_id(self):
        """Verifies the order record is committed (cart consumed) after payment."""
        client       = _make_client()
        mock_create  = AsyncMock(return_value=_order_mock())
        with (
            patch("app.mcp.tools.payment_tools.get_redis_client", new=AsyncMock(return_value=AsyncMock())),
            patch("app.orders.service.get_cart",     new=AsyncMock(return_value=_cart())),
            patch("app.orders.service.create_order", new=mock_create),
            patch("app.mcp.tools.payment_tools.AsyncSessionLocal", return_value=_db_session()),
        ):
            client.post("/mcp/tools/process_payment", json={
                "user_id": str(USER_ID), "payment_method_id": "pm_card_visa",
            })

        mock_create.assert_called_once()
        # Third positional arg is uuid.UUID(user_id)
        assert mock_create.call_args.args[2] == USER_ID

    def test_order_id_in_response_matches_created_order(self):
        client = _make_client()
        order  = _order_mock()
        with (
            patch("app.mcp.tools.payment_tools.get_redis_client", new=AsyncMock(return_value=AsyncMock())),
            patch("app.orders.service.get_cart",     new=AsyncMock(return_value=_cart())),
            patch("app.orders.service.create_order", new=AsyncMock(return_value=order)),
            patch("app.mcp.tools.payment_tools.AsyncSessionLocal", return_value=_db_session()),
        ):
            resp = client.post("/mcp/tools/process_payment", json={
                "user_id": str(USER_ID), "payment_method_id": "pm_card_visa",
            })

        assert resp.json()["order_id"] == str(ORDER_ID)

    def test_empty_cart_returns_400(self):
        client = _make_client()
        with (
            patch("app.mcp.tools.payment_tools.get_redis_client", new=AsyncMock(return_value=AsyncMock())),
            patch("app.orders.service.get_cart", new=AsyncMock(return_value=_empty_cart())),
        ):
            resp = client.post("/mcp/tools/process_payment", json={
                "user_id": str(USER_ID), "payment_method_id": "pm_card_visa",
            })

        assert resp.status_code == 400


# ── Notification tools ────────────────────────────────────────────────────────

class TestSendConfirmationEmail:
    def test_skips_gracefully_when_sendgrid_not_configured(self):
        """
        A committed order must never be invalidated by an email failure.
        Verifies the endpoint returns 200 (not 5xx) with sent=False and a reason.
        """
        client = _make_client()
        with patch("app.mcp.tools.notification_tools.settings") as mock_settings:
            mock_settings.sendgrid_api_key  = None
            mock_settings.sendgrid_from_email = "noreply@shopsense.com"
            resp = client.post("/mcp/tools/send_confirmation_email", json={
                "order_id": str(ORDER_ID), "user_email": "buyer@example.com",
            })

        assert resp.status_code == 200
        body = resp.json()
        assert body["sent"] is False
        assert body["reason"] == "sendgrid_not_configured"
        assert body["to"] == "buyer@example.com"


class TestSetPriceAlert:
    def test_stores_alert_and_returns_alert_set_true(self):
        client  = _make_client()
        db_row  = {"id": uuid.uuid4()}
        session = _db_session(first_row=db_row)
        with patch("app.mcp.tools.notification_tools.AsyncSessionLocal", return_value=session):
            resp = client.post("/mcp/tools/set_price_alert", json={
                "user_id":     str(USER_ID),
                "product_id":  str(PRODUCT_ID),
                "target_price": 70000.0,
                "user_email":  "buyer@example.com",
            })

        assert resp.status_code == 200
        body = resp.json()
        assert body["alert_set"]   is True
        assert body["target_price"] == 70000.0
        assert body["notify_at"]    == "buyer@example.com"

    def test_db_commit_called_to_persist_alert(self):
        client  = _make_client()
        db_row  = {"id": uuid.uuid4()}
        session = _db_session(first_row=db_row)
        with patch("app.mcp.tools.notification_tools.AsyncSessionLocal", return_value=session):
            client.post("/mcp/tools/set_price_alert", json={
                "user_id": str(USER_ID), "product_id": str(PRODUCT_ID),
                "target_price": 70000.0, "user_email": "buyer@example.com",
            })

        session.commit.assert_called_once()


# ── list_tools ────────────────────────────────────────────────────────────────

class TestListTools:
    _ALL_TOOLS = {
        "check_stock_status",
        "get_delivery_estimate",
        "get_frequently_bought_together",
        "add_to_cart",
        "get_saved_payment_methods",
        "calculate_order_total",
        "process_payment",
        "send_confirmation_email",
        "set_price_alert",
        "submit_review",
    }
    _WRITE_TOOLS = {
        "add_to_cart", "process_payment", "set_price_alert",
        "send_confirmation_email",  # auto-executes after payment — write-classified in registry
        "submit_review",
    }
    _READ_TOOLS  = _ALL_TOOLS - _WRITE_TOOLS

    def test_all_10_tools_are_returned(self):
        resp  = _make_client().get("/mcp/tools")
        assert resp.status_code == 200
        names = {t["name"] for t in resp.json()}
        assert names == self._ALL_TOOLS

    def test_every_tool_has_read_or_write_type(self):
        resp = _make_client().get("/mcp/tools")
        for tool in resp.json():
            assert tool["type"] in {"read", "write"}, (
                f"{tool['name']} is missing read/write classification"
            )

    def test_write_tools_are_classified_as_write(self):
        tools = {t["name"]: t for t in _make_client().get("/mcp/tools").json()}
        for name in self._WRITE_TOOLS:
            assert tools[name]["type"] == "write", f"{name} should be write"

    def test_read_tools_are_classified_as_read(self):
        tools = {t["name"]: t for t in _make_client().get("/mcp/tools").json()}
        for name in self._READ_TOOLS:
            assert tools[name]["type"] == "read", f"{name} should be read"
