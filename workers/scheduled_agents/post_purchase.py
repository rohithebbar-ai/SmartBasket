#!/usr/bin/env python3
"""
Post-purchase worker — Kafka consumer + background loops for review outreach
and price alert notifications.

Does NOT import from app/main.py or use the FastAPI app factory.

Consumes: order.delivered

Background tasks:
  check_outreach_queue — polls Redis sorted set 'review_outreach_queue' every 60s;
                         fires review emails 3 days after delivery
  check_price_alerts  — polls PostgreSQL price_alerts table every 600s;
                         fires price drop emails when current_price <= target_price
"""

import asyncio
import json
import logging
import time

from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaConnectionError
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from sqlalchemy import text

from app.config import settings
from app.database import AsyncSessionLocal
from app.redis_client import get_redis_client

log = logging.getLogger(__name__)

_REVIEW_QUEUE_KEY = "review_outreach_queue"
_PENDING_REVIEW_TTL = 7 * 24 * 3600   # 7 days — Redis key expiry
_OUTREACH_DELAY     = 3 * 24 * 3600   # 3 days — time-to-fire after delivery


# ── User / product helpers ─────────────────────────────────────────────────────

async def _get_user_email(user_id: str) -> str | None:
    try:
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(
                    text("SELECT email FROM users WHERE id = :uid LIMIT 1"),
                    {"uid": user_id},
                )
            ).mappings().first()
            return row["email"] if row else None
    except Exception as exc:
        log.warning("DB user lookup failed for %s: %s", user_id, exc)
        return None


async def _get_product_names(product_ids: list[str]) -> dict[str, str]:
    if not product_ids:
        return {}
    try:
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    text("SELECT id::text, name FROM products WHERE id = ANY(:ids)"),
                    {"ids": product_ids},
                )
            ).mappings().all()
            return {row["id"]: row["name"] for row in rows}
    except Exception as exc:
        log.warning("DB product name lookup failed: %s", exc)
        return {}


# ── Review outreach ────────────────────────────────────────────────────────────

async def handle_order_delivered(event: dict) -> None:
    order_id   = event.get("order_id")
    user_id    = event.get("user_id")
    product_ids = event.get("product_ids", [])
    if not order_id or not user_id:
        return

    payload = json.dumps({"order_id": order_id, "user_id": user_id, "product_ids": product_ids})
    trigger_time = time.time() + _OUTREACH_DELAY

    try:
        redis = get_redis_client()
        await redis.zadd(_REVIEW_QUEUE_KEY, {payload: trigger_time})

        # For demo/testing: short-delay copy fires after 30 s so the flow is testable.
        # Remove this before production.
        demo_payload = json.dumps({
            "order_id": order_id, "user_id": user_id,
            "product_ids": product_ids, "_demo": True,
        })
        await redis.zadd(_REVIEW_QUEUE_KEY, {demo_payload: time.time() + 30})

        log.info("Review outreach scheduled: order=%s user=%s", order_id, user_id)
    except Exception as exc:
        log.warning("Failed to schedule review outreach for order %s: %s", order_id, exc)


async def send_review_request(order_id: str, user_id: str, product_ids: list[str]) -> None:
    user_email = await _get_user_email(user_id)
    if not user_email:
        log.warning("send_review_request: no email found for user %s", user_id)
        return

    product_names = await _get_product_names(product_ids)

    if settings.sendgrid_api_key:
        for pid in product_ids:
            name = product_names.get(pid, "your recent purchase")
            html_body = f"""
            <h2>We'd love your feedback!</h2>
            <p>Hi there,</p>
            <p>How are you enjoying your <strong>{name}</strong>?</p>
            <p>Your review helps other shoppers make better decisions.</p>
            <p><a href="https://shopsense.app/reviews/{pid}?order={order_id}">
               Leave a review
            </a></p>
            <p>Thanks for shopping with ShopSense!</p>
            """
            message = Mail(
                from_email=settings.sendgrid_from_email,
                to_emails=user_email,
                subject=f"How was your {name}?",
                html_content=html_body,
            )
            try:
                SendGridAPIClient(settings.sendgrid_api_key).send(message)
                log.info("Review request sent: product=%s to=%s", pid, user_email)
            except Exception as exc:
                log.warning("SendGrid failed for review request (product=%s): %s", pid, exc)
    else:
        log.info("SendGrid not configured — skipping review email for user %s", user_id)

    # Set pending_review key so the agent surfaces a review prompt on next chat open
    try:
        redis = get_redis_client()
        await redis.set(
            f"pending_review:{user_id}",
            json.dumps(product_ids),
            ex=_PENDING_REVIEW_TTL,
        )
        log.debug("pending_review set for user %s", user_id)
    except Exception as exc:
        log.warning("Failed to set pending_review key for user %s: %s", user_id, exc)


async def check_outreach_queue() -> None:
    while True:
        try:
            redis = get_redis_client()
            now = time.time()
            items = await redis.zrangebyscore(_REVIEW_QUEUE_KEY, 0, now)
            for item in items:
                try:
                    raw = item if isinstance(item, str) else item.decode("utf-8")
                    data = json.loads(raw)
                    await send_review_request(
                        data["order_id"], data["user_id"], data["product_ids"]
                    )
                    await redis.zrem(_REVIEW_QUEUE_KEY, item)
                except Exception as exc:
                    log.warning("Failed to process outreach item: %s", exc)
        except Exception as exc:
            log.warning("Outreach queue check failed: %s", exc)
        await asyncio.sleep(60)


# ── Price alert checking ───────────────────────────────────────────────────────

async def _send_price_drop_email(
    alert_id: str, user_email: str, product_name: str, current_price: float
) -> None:
    if not settings.sendgrid_api_key:
        log.info("SendGrid not configured — skipping price drop email for %s", user_email)
        return
    html_body = f"""
    <h2>Good news — your price alert triggered!</h2>
    <p><strong>{product_name}</strong> is now <strong>₹{current_price:,.0f}</strong>!</p>
    <p><a href="https://shopsense.app/search?q={product_name}">Shop now</a></p>
    <p style="color:#666;font-size:12px;">
      You set a price alert on ShopSense. Reply to unsubscribe.
    </p>
    """
    message = Mail(
        from_email=settings.sendgrid_from_email,
        to_emails=user_email,
        subject=f"Price drop: {product_name} is now ₹{current_price:,.0f}",
        html_content=html_body,
    )
    try:
        SendGridAPIClient(settings.sendgrid_api_key).send(message)
        log.info(
            "Price drop email sent: alert=%s to=%s product=%s price=%.0f",
            alert_id, user_email, product_name, current_price,
        )
    except Exception as exc:
        log.warning("SendGrid failed for price alert %s: %s", alert_id, exc)


async def check_price_alerts() -> None:
    while True:
        try:
            async with AsyncSessionLocal() as db:
                rows = (
                    await db.execute(text("""
                        SELECT pa.id::text AS id, pa.user_email, pa.target_price,
                               p.name, CAST(p.current_price AS FLOAT) AS current_price
                        FROM price_alerts pa
                        JOIN products p ON p.id = pa.product_id
                        WHERE pa.is_active = TRUE
                          AND p.current_price <= pa.target_price
                    """))
                ).mappings().all()

                for row in rows:
                    await _send_price_drop_email(
                        alert_id=row["id"],
                        user_email=row["user_email"],
                        product_name=row["name"],
                        current_price=row["current_price"],
                    )
                    try:
                        await db.execute(
                            text("""
                                UPDATE price_alerts
                                SET is_active = FALSE, triggered_at = NOW()
                                WHERE id = :id
                            """),
                            {"id": row["id"]},
                        )
                    except Exception as exc:
                        log.warning("Failed to deactivate price alert %s: %s", row["id"], exc)

                if rows:
                    await db.commit()
                    log.info("Price alert check: %d alert(s) triggered and deactivated", len(rows))
        except Exception as exc:
            log.warning("Price alert check failed: %s", exc)
        await asyncio.sleep(600)


# ── Kafka consumer loop ────────────────────────────────────────────────────────

async def _kafka_consumer_loop() -> None:
    topic = settings.kafka_topic_order_delivered
    while True:
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=settings.kafka_bootstrap_servers_list,
            group_id=f"{settings.kafka_consumer_group_id}-post-purchase",
            auto_offset_reset=settings.kafka_auto_offset_reset,
            value_deserializer=lambda b: json.loads(b.decode("utf-8")),
            enable_auto_commit=True,
        )
        try:
            await consumer.start()
            log.info("Post-purchase consumer started on topic: %s", topic)
            async for msg in consumer:
                try:
                    await handle_order_delivered(msg.value)
                except Exception:
                    log.warning(
                        "Error processing order.delivered message: %s",
                        msg.value, exc_info=True,
                    )
        except asyncio.CancelledError:
            log.info("Post-purchase consumer shutting down")
            break
        except KafkaConnectionError:
            log.warning("Kafka unavailable — retrying in 10s")
            await asyncio.sleep(10)
        except Exception:
            log.warning("Post-purchase consumer error — retrying in 5s", exc_info=True)
            await asyncio.sleep(5)
        finally:
            try:
                await consumer.stop()
            except Exception:
                pass


# ── Public entry point ─────────────────────────────────────────────────────────

async def run_post_purchase_worker() -> None:
    """
    Starts all three post-purchase tasks concurrently.
    Called by workers/run_workers.py. Runs until the process exits.
    """
    log.info("Post-purchase worker starting")
    await asyncio.gather(
        _kafka_consumer_loop(),
        check_outreach_queue(),
        check_price_alerts(),
    )
