"""
price.updated consumer — recalculates Redis cart totals when a product price changes.

When the pricing engine publishes price.updated for a product, this consumer:
  1. Scans Redis for all cart keys (cart:*)
  2. For each cart that contains the updated product, overwrites the item's
     unit_price with the new price
  3. The next get_cart() call will reflect the updated total automatically

Runs as a background asyncio task started in app/main.py lifespan.
"""

import asyncio
import json
import logging
import uuid
from decimal import Decimal

from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaConnectionError

from app.config import settings
from app.redis_client import get_redis_client

logger = logging.getLogger(__name__)

_consumer_task: asyncio.Task | None = None


async def _recalculate_carts(product_id: str, new_price: Decimal) -> None:
    """
    Scans all cart:{user_id} keys in Redis and updates unit_price for
    any cart that contains the given product_id.
    Uses SCAN (non-blocking) rather than KEYS to avoid blocking the Redis event loop.
    """
    redis = get_redis_client()
    updated = 0
    try:
        async for key in redis.scan_iter("cart:*"):
            raw = await redis.hget(key, product_id)
            if raw is None:
                continue
            item = json.loads(raw)
            item["unit_price"] = str(new_price)
            await redis.hset(key, product_id, json.dumps(item))
            updated += 1
        if updated:
            logger.info(
                "price.updated: recalculated %d cart(s) for product %s → %s",
                updated, product_id, new_price,
            )
    except Exception:
        logger.warning("Cart recalculation failed for product %s", product_id, exc_info=True)


async def _consume_loop() -> None:
    """
    Long-running coroutine. Reconnects automatically on transient Kafka errors.
    Exits cleanly when cancelled (app shutdown).
    """
    while True:
        consumer = AIOKafkaConsumer(
            settings.kafka_topic_price_updated,
            bootstrap_servers=settings.kafka_bootstrap_servers_list,
            group_id=f"{settings.kafka_consumer_group_id}-orders",
            auto_offset_reset=settings.kafka_auto_offset_reset,
            value_deserializer=lambda b: json.loads(b.decode("utf-8")),
            enable_auto_commit=True,
        )
        try:
            await consumer.start()
            logger.info("price.updated consumer started")
            async for msg in consumer:
                try:
                    data       = msg.value
                    product_id = data.get("product_id")
                    new_price  = data.get("new_price")
                    if product_id and new_price is not None:
                        await _recalculate_carts(product_id, Decimal(str(new_price)))
                except Exception:
                    logger.warning("Failed to process price.updated message", exc_info=True)
        except asyncio.CancelledError:
            logger.info("price.updated consumer shutting down")
            break
        except KafkaConnectionError:
            logger.warning("Kafka unavailable — retrying in 10s")
            await asyncio.sleep(10)
        except Exception:
            logger.warning("price.updated consumer error — retrying in 5s", exc_info=True)
            await asyncio.sleep(5)
        finally:
            try:
                await consumer.stop()
            except Exception:
                pass


async def start_consumer() -> None:
    """Spawns the consumer loop as a background asyncio task."""
    global _consumer_task
    _consumer_task = asyncio.create_task(_consume_loop(), name="price-updated-consumer")
    logger.info("price.updated consumer task created")


async def stop_consumer() -> None:
    """Cancels the consumer task and waits for it to finish cleanly."""
    global _consumer_task
    if _consumer_task and not _consumer_task.done():
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass
        _consumer_task = None
    logger.info("price.updated consumer stopped")
