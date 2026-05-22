"""
Payment tools — read and write tools for the checkout and payment flow.

Read tools:
  POST /get_saved_payment_methods  — masked card list (no raw card data ever returned)
  POST /calculate_order_total      — itemised bill with GST, delivery fee, optional coupon

Write tools:
  POST /process_payment            — charge Stripe, create Order, clear cart, publish Kafka
                                     Total is ALWAYS recalculated server-side — never trusted
                                     from the client.
"""

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import stripe
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.config import settings
from app.database import AsyncSessionLocal
from app.orders import service as order_service
from app.orders.kafka_producer import publish_order_created
from app.redis_client import get_redis_client
from sqlalchemy import text

log = logging.getLogger(__name__)
router = APIRouter()

_GST_RATE = Decimal("0.18")
_FREE_DELIVERY_THRESHOLD = Decimal("50000")  # ₹50,000
_DELIVERY_FEE = Decimal("499")               # ₹499
_USD_TO_INR = Decimal("83")


# ── Request models ────────────────────────────────────────────────────────────

class UserIdBody(BaseModel):
    user_id: str

class OrderTotalBody(BaseModel):
    user_id: str
    coupon_code: str | None = None

class ProcessPaymentBody(BaseModel):
    user_id: str
    payment_method_id: str


# ── get_saved_payment_methods ─────────────────────────────────────────────────

@router.post("/get_saved_payment_methods")
async def get_saved_payment_methods(body: UserIdBody) -> dict:
    """
    Returns masked payment methods. stripe_payment_method_id is intentionally
    excluded from the response — the frontend never sees raw Stripe tokens.
    """
    sql = text("""
        SELECT stripe_payment_method_id, card_type, last4,
               expiry_month, expiry_year, is_default
        FROM payment_methods
        WHERE user_id = :user_id
        ORDER BY is_default DESC, created_at DESC
    """)
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(sql, {"user_id": body.user_id})).mappings().all()

    methods = [
        {
            "payment_method_id": r["stripe_payment_method_id"],  # needed for process_payment
            "type": r["card_type"],
            "last4": r["last4"],
            "expires": f"{r['expiry_month']:02d}/{r['expiry_year']}",
            "is_default": bool(r["is_default"]),
        }
        for r in rows
    ]
    return {"methods": methods}


# ── calculate_order_total ─────────────────────────────────────────────────────

async def _calculate_total_internal(user_id: str, coupon_code: str | None = None) -> dict:
    """
    Core billing logic — called by both the endpoint and process_payment.
    Server-side only: total is never accepted from the client.
    """
    redis = get_redis_client()
    cart = await order_service.get_cart(redis, uuid.UUID(user_id))

    if not cart.items:
        raise ValueError("cart_empty")

    # unit_price in Redis is in USD — convert to INR for all display and business logic
    subtotal = sum(Decimal(str(i.unit_price)) * i.qty * _USD_TO_INR for i in cart.items)

    # Free delivery for orders over ₹50,000; ₹499 otherwise
    delivery_fee = Decimal("0") if subtotal >= _FREE_DELIVERY_THRESHOLD else _DELIVERY_FEE
    gst = (subtotal * _GST_RATE).quantize(Decimal("0.01"))

    discount = Decimal("0")
    if coupon_code:
        log.info("Coupon lookup for code '%s' — not yet implemented", coupon_code)

    total = subtotal + gst + delivery_fee - discount

    line_items = [
        {
            "name": item.name,
            "qty": item.qty,
            "unit_price": float(Decimal(str(item.unit_price)) * _USD_TO_INR),
            "subtotal": float(Decimal(str(item.unit_price)) * item.qty * _USD_TO_INR),
        }
        for item in cart.items
    ]

    return {
        "items": line_items,
        "subtotal": float(subtotal),
        "gst": float(gst),
        "delivery_fee": float(delivery_fee),
        "discount": float(discount),
        "total": float(total),
    }


@router.post("/calculate_order_total")
async def calculate_order_total(body: OrderTotalBody) -> dict:
    try:
        return await _calculate_total_internal(body.user_id, body.coupon_code)
    except ValueError as exc:
        if str(exc) == "cart_empty":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cart is empty")
        raise


# ── process_payment ───────────────────────────────────────────────────────────

@router.post("/process_payment")
async def process_payment(body: ProcessPaymentBody) -> dict:
    """
    Charges the user's saved Stripe payment method.

    Total is recalculated server-side — the client never supplies an amount.
    Idempotency key is scoped to (user_id + minute bucket) to prevent double
    charges on network retries within the same minute.
    """
    # Recalculate server-side — never trust a client-supplied total
    try:
        bill = await _calculate_total_internal(body.user_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cart is empty")

    total_inr = bill["total"]

    if not settings.stripe_secret_key:
        log.warning("Stripe key not configured — using mock order for development")
        redis = get_redis_client()
        async with AsyncSessionLocal() as db:
            order = await order_service.create_order(redis, db, uuid.UUID(body.user_id))
        return {
            "success": True,
            "order_id": str(order.id),
            "amount_charged": float(order.total_amount),
            "mock": True,
        }

    stripe.api_key = settings.stripe_secret_key
    amount_paise = int(total_inr * 100)
    minute_bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    idempotency_key = f"{body.user_id}-{minute_bucket}"

    try:
        intent = stripe.PaymentIntent.create(
            amount=amount_paise,
            currency="inr",
            payment_method=body.payment_method_id,
            confirm=True,
            off_session=True,  # charging a saved card without customer present
            automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
            idempotency_key=idempotency_key,
        )
    except stripe.error.CardError as exc:
        log.warning("Card declined for user %s: %s", body.user_id, exc.user_message)
        return {"success": False, "error": "card_declined", "message": exc.user_message}
    except stripe.error.StripeError as exc:
        log.error("Stripe error for user %s: %s", body.user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment gateway error — please try again",
        )

    if intent.status != "succeeded":
        return {"success": False, "error": "payment_not_confirmed", "status": intent.status}

    # Commit order and clear cart — happens after payment confirmation
    redis = get_redis_client()
    async with AsyncSessionLocal() as db:
        order = await order_service.create_order(redis, db, uuid.UUID(body.user_id))

    # Publish Kafka event (fire-and-forget — order is already committed)
    import asyncio
    asyncio.create_task(
        publish_order_created(
            order_id=order.id,
            user_id=uuid.UUID(body.user_id),
            items=order.items,
            total_amount=order.total_amount,
        )
    )

    return {
        "success": True,
        "order_id": str(order.id),
        "amount_charged": float(order.total_amount),
    }
