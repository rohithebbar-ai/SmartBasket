"""
Notification tools — email and alert tools for the post-purchase flow.

  POST /send_confirmation_email  — SendGrid receipt after successful payment.
                                   Auto-executes after process_payment; no separate
                                   await_confirmation gate for this tool.
  POST /set_price_alert          — saves a price_alerts row; write tool with gate.
  POST /submit_review            — stub (real implementation in Day 15 worker).
"""

import logging

from fastapi import APIRouter
from pydantic import BaseModel
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from sqlalchemy import text

from app.config import settings
from app.database import AsyncSessionLocal

log = logging.getLogger(__name__)
router = APIRouter()


# ── Request models ────────────────────────────────────────────────────────────

class ConfirmationEmailBody(BaseModel):
    order_id: str
    user_email: str

class PriceAlertBody(BaseModel):
    user_id: str
    product_id: str
    target_price: float
    user_email: str

class SubmitReviewBody(BaseModel):
    user_id: str
    product_id: str
    order_id: str


# ── send_confirmation_email ───────────────────────────────────────────────────

_ORDER_SQL = text("""
    SELECT id, items, total_amount, created_at
    FROM orders
    WHERE id = :order_id
    LIMIT 1
""")


@router.post("/send_confirmation_email")
async def send_confirmation_email(body: ConfirmationEmailBody) -> dict:
    """
    Sends an HTML receipt via SendGrid.
    Never raises — a committed order must never be invalidated by an email failure.
    """
    if not settings.sendgrid_api_key:
        log.warning("SendGrid key not configured — skipping confirmation email")
        return {"sent": False, "to": body.user_email, "reason": "sendgrid_not_configured"}

    async with AsyncSessionLocal() as db:
        order_row = (
            await db.execute(_ORDER_SQL, {"order_id": body.order_id})
        ).mappings().first()

    if order_row is None:
        log.warning("send_confirmation_email: order %s not found", body.order_id)
        return {"sent": False, "to": body.user_email, "reason": "order_not_found"}

    short_id = str(order_row["id"])[:8].upper()
    items = order_row["items"] or []
    total = float(order_row["total_amount"])

    items_html = "".join(
        f"<li>{item.get('name', 'Item')} × {item.get('qty', 1)} "
        f"— ₹{float(item.get('price_at_order', 0)):,.0f}</li>"
        for item in items
    )

    html_body = f"""
    <h2>Your ShopSense order is confirmed! 🎉</h2>
    <p>Order ID: <strong>#{short_id}</strong></p>
    <h3>Items ordered:</h3>
    <ul>{items_html}</ul>
    <p><strong>Total paid: ₹{total:,.0f}</strong></p>
    <p>Estimated delivery: 3-5 business days</p>
    <hr>
    <p style="color:#666;font-size:12px;">
      Thank you for shopping with ShopSense.
      Questions? Reply to this email.
    </p>
    """

    message = Mail(
        from_email=settings.sendgrid_from_email,
        to_emails=body.user_email,
        subject=f"Order confirmed — #{short_id}",
        html_content=html_body,
    )

    try:
        SendGridAPIClient(settings.sendgrid_api_key).send(message)
        log.info("Confirmation email sent: order=%s to=%s", short_id, body.user_email)
        return {"sent": True, "to": body.user_email}
    except Exception as exc:
        log.error("SendGrid failed for order %s: %s", short_id, exc)
        return {"sent": False, "to": body.user_email, "reason": str(exc)}


# ── set_price_alert ───────────────────────────────────────────────────────────

@router.post("/set_price_alert")
async def set_price_alert(body: PriceAlertBody) -> dict:
    sql = text("""
        INSERT INTO price_alerts
            (user_id, product_id, target_price, user_email, is_active, created_at)
        VALUES
            (:user_id, :product_id, :target_price, :user_email, TRUE, NOW())
        RETURNING id
    """)
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(sql, {
                "user_id": body.user_id,
                "product_id": body.product_id,
                "target_price": body.target_price,
                "user_email": body.user_email,
            })
        ).mappings().first()
        await db.commit()

    return {
        "alert_set": True,
        "target_price": body.target_price,
        "notify_at": body.user_email,
    }


# ── submit_review (stub) ──────────────────────────────────────────────────────

@router.post("/submit_review")
async def submit_review(body: SubmitReviewBody) -> dict:
    """
    Stub — real implementation queues a review request after order delivery
    confirmation via the post-purchase worker (Redis delay queue, 3-day trigger).
    """
    return {
        "queued": True,
        "message": "Review request will be sent after delivery confirmation.",
    }
