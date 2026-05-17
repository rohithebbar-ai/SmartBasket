import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from aiokafka import AIOKafkaProducer

from app.config import settings

logger = logging.getLogger(__name__)

_producer: AIOKafkaProducer | None = None


async def _get_producer() -> AIOKafkaProducer:
    global _producer
    if _producer is None:
        _producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers_list,
            # Serialize to UTF-8 JSON bytes
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            # product_id string key — ensures partition affinity per product
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            # Wait for leader ack only (fast, sufficient durability for demand signals)
            acks=1,
        )
        await _producer.start()
    return _producer


async def close_producer() -> None:
    """Called during app shutdown to flush and close the producer cleanly."""
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None


async def publish_product_viewed(
    product_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    session_id: str | None = None,
    source: str = "api",
) -> None:
    """
    Publishes a product.viewed event. Keyed by product_id so all view events
    for the same product land on the same partition in arrival order.

    Never raises — Kafka unavailability must not fail a product page load.
    """
    payload = {
        "product_id": str(product_id),
        "source": source,
    }
    # No PII: user_id is an opaque UUID, no name/email in the payload.
    if user_id is not None:
        payload["user_id"] = str(user_id)
    if session_id is not None:
        payload["session_id"] = session_id

    try:
        producer = await _get_producer()
        await producer.send_and_wait(
            settings.kafka_topic_product_viewed,
            value=payload,
            key=str(product_id),
        )
        logger.debug("product.viewed published: product_id=%s", product_id)
    except Exception:
        # Log and swallow — demand signal loss is acceptable; page failure is not.
        logger.warning("Failed to publish product.viewed for %s", product_id, exc_info=True)


async def publish_product_created(product_id: uuid.UUID) -> None:
    """
    Publishes a product.created event consumed by the embedding generation worker.
    Keyed by product_id for partition affinity.

    Never raises — embedding generation will catch up on retry.
    """
    payload = {"product_id": str(product_id)}
    try:
        producer = await _get_producer()
        await producer.send_and_wait(
            settings.kafka_topic_product_created,
            value=payload,
            key=str(product_id),
        )
        logger.debug("product.created published: product_id=%s", product_id)
    except Exception:
        logger.warning("Failed to publish product.created for %s", product_id, exc_info=True)
