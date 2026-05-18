"""
product.viewed consumer — increments view counters in Redis.

On each product.viewed event:
  INCR  views:{product_id}    — atomic view count
  EXPIRE views:{product_id}   24h  — TTL resets on every view, matching a sliding window

The counter is the demand signal read by the pricing engine every 120s.
A product with views:{id} >= settings.pricing_demand_threshold triggers a
price increase; below it triggers a reduction.

Runs as a background asyncio task started in app/main.py lifespan alongside
the orders price.updated consumer.
"""

import asyncio
import json
import logging

from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaConnectionError

from app.config import settings
from app.redis_client import get_redis_client

log = logging.getLogger(__name__)

_VIEWS_TTL = 24 * 60 * 60  # 24 hours in seconds

_consumer_task: asyncio.Task | None = None


async def _increment_view(product_id: str) -> None:
    redis = get_redis_client()
    key = f"views:{product_id}"
    await redis.incr(key)
    await redis.expire(key, _VIEWS_TTL)


async def _consume_loop() -> None:
    """
    Long-running coroutine. Reconnects automatically on transient Kafka errors.
    Exits cleanly when cancelled (app shutdown).
    """
    while True:
        consumer = AIOKafkaConsumer(
            settings.kafka_topic_product_viewed,
            bootstrap_servers=settings.kafka_bootstrap_servers_list,
            group_id=f"{settings.kafka_consumer_group_id}-search",
            auto_offset_reset=settings.kafka_auto_offset_reset,
            value_deserializer=lambda b: json.loads(b.decode("utf-8")),
            enable_auto_commit=True,
        )
        try:
            await consumer.start()
            log.info("product.viewed consumer started")
            async for msg in consumer:
                try:
                    product_id = msg.value.get("product_id")
                    if product_id:
                        await _increment_view(str(product_id))
                        log.debug("views:%s incremented", product_id)
                except Exception:
                    log.warning("Failed to process product.viewed message", exc_info=True)
        except asyncio.CancelledError:
            log.info("product.viewed consumer shutting down")
            break
        except KafkaConnectionError:
            log.warning("Kafka unavailable — retrying in 10s")
            await asyncio.sleep(10)
        except Exception:
            log.warning("product.viewed consumer error — retrying in 5s", exc_info=True)
            await asyncio.sleep(5)
        finally:
            try:
                await consumer.stop()
            except Exception:
                pass


async def start_consumer() -> None:
    """Spawns the consumer loop as a background asyncio task."""
    global _consumer_task
    _consumer_task = asyncio.create_task(_consume_loop(), name="product-viewed-consumer")
    log.info("product.viewed consumer task created")


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
    log.info("product.viewed consumer stopped")
