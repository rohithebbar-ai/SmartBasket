import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from aiokafka import AIOKafkaProducer

from app.config import settings

logger = logging.getLogger(__name__)

_producer: AIOKafkaProducer | None = None


async def _get_producer() -> AIOKafkaProducer:
    global _producer
    if _producer is None:
        _producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers_list,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            acks=1,
        )
        await _producer.start()
    return _producer


async def close_producer() -> None:
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None


async def publish_cart_updated(user_id: uuid.UUID, cart_total: Decimal) -> None:
    """
    Published after every add/remove. Consumed by the personalisation worker
    to track browsing intent. No PII beyond the opaque user UUID.
    Never raises — cart UI must not break on Kafka failure.
    """
    payload = {
        "user_id": str(user_id),
        "cart_total": float(cart_total),
    }
    try:
        producer = await _get_producer()
        await producer.send_and_wait(
            settings.kafka_topic_cart_updated,
            value=payload,
            key=str(user_id),
        )
        logger.debug("cart.updated published: user_id=%s total=%s", user_id, cart_total)
    except Exception:
        logger.warning("Failed to publish cart.updated for user %s", user_id, exc_info=True)


async def publish_order_created(
    order_id: uuid.UUID,
    user_id: uuid.UUID,
    items: list[dict],
    total_amount: Decimal,
) -> None:
    """
    Published after a successful checkout. Highest-weight personalisation signal.
    items list contains product_id, name, qty — no prices (avoid financial data in Kafka).
    Never raises — a committed order must not be invalidated by a Kafka failure.
    """
    payload = {
        "order_id": str(order_id),
        "user_id": str(user_id),
        "total_amount": float(total_amount),
        "items": [
            {"product_id": str(i["product_id"]), "qty": i["qty"]}
            for i in items
        ],
    }
    try:
        producer = await _get_producer()
        await producer.send_and_wait(
            settings.kafka_topic_order_created,
            value=payload,
            key=str(order_id),
        )
        logger.debug("order.created published: order_id=%s user_id=%s", order_id, user_id)
    except Exception:
        logger.warning("Failed to publish order.created for order %s", order_id, exc_info=True)


async def publish_order_delivered(
    order_id: str,
    user_id: str,
    product_ids: list[str],
) -> None:
    """
    Published after an order is marked as delivered via the admin status endpoint.
    Consumed by the post-purchase worker to schedule a 3-day review reminder.
    product_ids are extracted from the order.items JSONB snapshot.
    Never raises — delivery confirmation must not be rolled back by a Kafka failure.
    """
    payload = {
        "event_type": "order.delivered",
        "order_id": order_id,
        "user_id": user_id,
        "product_ids": product_ids,
        "delivered_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        producer = await _get_producer()
        await producer.send_and_wait(
            settings.kafka_topic_order_delivered,
            value=payload,
            key=order_id,
        )
        logger.debug("order.delivered published: order_id=%s user_id=%s", order_id, user_id)
    except Exception:
        logger.warning("Failed to publish order.delivered for order %s", order_id, exc_info=True)
