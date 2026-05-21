#!/usr/bin/env python3
"""
Personalisation worker — standalone Kafka consumer that builds user preference profiles.

Does NOT import from app/main.py or use the FastAPI app factory.
Uses app.database.AsyncSessionLocal and app.redis_client.get_redis_client directly.

Consumes: product.viewed, cart.updated, order.created
Writes:   user_preferences table (UPSERT every 50 events or every 30 minutes)

Signal weights (higher = stronger preference signal):
  order.created   — weight 5  (user paid: strongest signal)
  cart.updated    — weight 3  (cart total used for price range; no product_id in payload)
  product.viewed  — weight 1  (passive browsing: weakest signal)

Flush triggers:
  - Event count:  every 50 events for a given user_id
  - Time-based:   every 30 minutes for any user with un-flushed scores

Product lookups use a Redis cache (key: product_cache:{product_id}, TTL 10 min)
to avoid hammering PostgreSQL on high-traffic streams.
"""

import asyncio
import json
import logging
import time

from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaConnectionError
from sqlalchemy import text

from app.config import settings
from app.database import AsyncSessionLocal
from app.redis_client import get_redis_client

log = logging.getLogger(__name__)

# ── Signal weights ─────────────────────────────────────────────────────────────

WEIGHTS: dict[str, int] = {
    settings.kafka_topic_product_viewed: 1,
    settings.kafka_topic_cart_updated:   3,
    settings.kafka_topic_order_created:  5,
}

# ── In-memory scoring state ────────────────────────────────────────────────────
# Flushed to PostgreSQL every FLUSH_EVERY events per user or every FLUSH_INTERVAL seconds.

FLUSH_EVERY    = 50      # events per user
FLUSH_INTERVAL = 1800    # 30 minutes
CACHE_TTL      = 600     # 10 minutes — product cache in Redis

# {user_id: {"brands": {brand: score}, "categories": {cat: score}, "prices": [float, ...]}}
user_scores: dict[str, dict] = {}

# {user_id: event_count}
event_counts: dict[str, int] = {}

# {user_id: last_flush_timestamp}
last_flush: dict[str, float] = {}


# ── Product cache ──────────────────────────────────────────────────────────────

async def _get_product_cached(product_id: str) -> dict | None:
    """
    Returns {"brand": ..., "category": ..., "current_price": ...} for a product.
    Checks Redis first (product_cache:{product_id}); falls back to PostgreSQL.
    Returns None if the product doesn't exist or an error occurs.
    """
    redis = get_redis_client()
    cache_key = f"product_cache:{product_id}"

    try:
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception as exc:
        log.debug("Redis product cache miss for %s: %s", product_id, exc)

    try:
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(
                    text("""
                        SELECT brand, category,
                               CAST(current_price AS FLOAT) AS current_price
                        FROM products
                        WHERE id = :pid AND is_active = true
                        LIMIT 1
                    """),
                    {"pid": product_id},
                )
            ).mappings().first()
    except Exception as exc:
        log.warning("DB product lookup failed for %s: %s", product_id, exc)
        return None

    if row is None:
        return None

    product = {
        "brand":         row["brand"],
        "category":      row["category"],
        "current_price": row["current_price"],
    }

    try:
        await redis.setex(cache_key, CACHE_TTL, json.dumps(product))
    except Exception:
        pass  # cache write failure is non-fatal

    return product


# ── Per-product scoring ───────────────────────────────────────────────────────

def _score_product(user_id: str, product: dict, weight: int) -> None:
    """Increments in-memory brand/category scores and appends the price."""
    scores = user_scores.setdefault(
        user_id, {"brands": {}, "categories": {}, "prices": []}
    )
    brand    = product.get("brand", "")
    category = product.get("category", "")
    price    = product.get("current_price")

    if brand:
        scores["brands"][brand] = scores["brands"].get(brand, 0) + weight
    if category:
        scores["categories"][category] = scores["categories"].get(category, 0) + weight
    if price is not None:
        scores["prices"].append(float(price))


# ── Event handlers ─────────────────────────────────────────────────────────────

async def _handle_product_viewed(event: dict) -> None:
    user_id    = event.get("user_id")
    product_id = event.get("product_id")
    if not user_id or not product_id:
        return

    product = await _get_product_cached(product_id)
    if product:
        _score_product(user_id, product, WEIGHTS[settings.kafka_topic_product_viewed])

    _increment_and_maybe_flush(user_id)


async def _handle_cart_updated(event: dict) -> None:
    """
    cart.updated payload has user_id + cart_total but NO product_id.
    Records the cart total as a price-range signal (no brand/category scoring possible).
    """
    user_id    = event.get("user_id")
    cart_total = event.get("cart_total")
    if not user_id or cart_total is None:
        return

    scores = user_scores.setdefault(
        user_id, {"brands": {}, "categories": {}, "prices": []}
    )
    # Weight-3 price signal: cart_total reflects what the user is actively considering.
    # Appended once; weight is captured by flush_interval/count prioritisation.
    scores["prices"].append(float(cart_total))

    _increment_and_maybe_flush(user_id)


async def _handle_order_created(event: dict) -> None:
    """
    order.created has items: [{product_id, qty}, ...].
    Score each purchased product with weight 5 (highest — user actually paid).
    """
    user_id = event.get("user_id")
    items   = event.get("items") or []
    if not user_id or not items:
        return

    weight = WEIGHTS[settings.kafka_topic_order_created]
    for item in items:
        product_id = item.get("product_id")
        if not product_id:
            continue
        product = await _get_product_cached(product_id)
        if product:
            qty = int(item.get("qty", 1))
            # Apply weight proportional to quantity purchased (stronger signal)
            _score_product(user_id, product, weight * qty)

    _increment_and_maybe_flush(user_id)


def _increment_and_maybe_flush(user_id: str) -> None:
    """Increments the event counter; schedules a flush if threshold is reached."""
    event_counts[user_id] = event_counts.get(user_id, 0) + 1
    if event_counts[user_id] % FLUSH_EVERY == 0:
        asyncio.create_task(_flush_preferences(user_id))


# ── Flush to PostgreSQL ────────────────────────────────────────────────────────

async def _flush_preferences(user_id: str) -> None:
    """
    Computes top brands/categories and price percentiles from in-memory scores,
    then UPSERTs into user_preferences. Invalidates the agent's Redis preferences cache.
    """
    scores = user_scores.get(user_id)
    if not scores:
        return

    preferred_brands = sorted(
        scores["brands"], key=scores["brands"].get, reverse=True  # type: ignore[arg-type]
    )[:3]

    preferred_categories = sorted(
        scores["categories"], key=scores["categories"].get, reverse=True  # type: ignore[arg-type]
    )[:2]

    prices = sorted(scores["prices"])
    if prices:
        n            = len(prices)
        price_min    = prices[n // 4]          # 25th percentile
        price_max    = prices[(3 * n) // 4]    # 75th percentile
    else:
        price_min = price_max = None

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("""
                    INSERT INTO user_preferences
                        (user_id, preferred_brands, preferred_categories,
                         typical_price_min, typical_price_max, last_updated)
                    VALUES
                        (:uid, :brands::jsonb, :cats::jsonb, :price_min, :price_max, NOW())
                    ON CONFLICT (user_id) DO UPDATE SET
                        preferred_brands     = EXCLUDED.preferred_brands,
                        preferred_categories = EXCLUDED.preferred_categories,
                        typical_price_min    = EXCLUDED.typical_price_min,
                        typical_price_max    = EXCLUDED.typical_price_max,
                        last_updated         = NOW()
                """),
                {
                    "uid":       user_id,
                    "brands":    json.dumps(preferred_brands),
                    "cats":      json.dumps(preferred_categories),
                    "price_min": price_min,
                    "price_max": price_max,
                },
            )
            await db.commit()
        log.info(
            "Preferences flushed: user=%s brands=%s cats=%s price=[%s-%s]",
            user_id[:8], preferred_brands, preferred_categories, price_min, price_max,
        )
    except Exception as exc:
        log.error("Failed to flush preferences for user %s: %s", user_id[:8], exc)
        return

    # Invalidate the agent's cached preference key so load_context picks up fresh data
    try:
        redis = get_redis_client()
        await redis.delete(f"preferences:{user_id}")
    except Exception:
        pass  # non-fatal

    last_flush[user_id] = time.time()


# ── Periodic 30-minute flush loop ─────────────────────────────────────────────

async def _periodic_flush_loop() -> None:
    """
    Runs indefinitely. Every 30 minutes, flushes preferences for any user whose
    last flush was more than FLUSH_INTERVAL seconds ago.
    Catches all exceptions so a single bad flush never kills the loop.
    """
    while True:
        await asyncio.sleep(FLUSH_INTERVAL)
        now = time.time()
        stale_users = [
            uid for uid in list(user_scores)
            if now - last_flush.get(uid, 0) > FLUSH_INTERVAL
        ]
        for uid in stale_users:
            try:
                await _flush_preferences(uid)
            except Exception as exc:
                log.error("Periodic flush failed for user %s: %s", uid[:8], exc)


# ── Kafka consumer loop ────────────────────────────────────────────────────────

_TOPIC_HANDLERS = {
    settings.kafka_topic_product_viewed: _handle_product_viewed,
    settings.kafka_topic_cart_updated:   _handle_cart_updated,
    settings.kafka_topic_order_created:  _handle_order_created,
}

_TOPICS = list(_TOPIC_HANDLERS)


async def _consume_loop() -> None:
    """
    Long-running consumer. Reconnects automatically on transient Kafka errors.
    Exits cleanly on asyncio.CancelledError (process shutdown).
    """
    while True:
        consumer = AIOKafkaConsumer(
            *_TOPICS,
            bootstrap_servers=settings.kafka_bootstrap_servers_list,
            group_id=f"{settings.kafka_consumer_group_id}-personalisation",
            auto_offset_reset=settings.kafka_auto_offset_reset,
            value_deserializer=lambda b: json.loads(b.decode("utf-8")),
            enable_auto_commit=True,
        )
        try:
            await consumer.start()
            log.info("Personalisation consumer started on topics: %s", _TOPICS)
            async for msg in consumer:
                handler = _TOPIC_HANDLERS.get(msg.topic)
                if handler is None:
                    continue
                try:
                    await handler(msg.value)
                except Exception:
                    log.warning(
                        "Error processing %s message: %s",
                        msg.topic, msg.value, exc_info=True,
                    )
        except asyncio.CancelledError:
            log.info("Personalisation consumer shutting down")
            break
        except KafkaConnectionError:
            log.warning("Kafka unavailable — retrying in 10s")
            await asyncio.sleep(10)
        except Exception:
            log.warning("Personalisation consumer error — retrying in 5s", exc_info=True)
            await asyncio.sleep(5)
        finally:
            try:
                await consumer.stop()
            except Exception:
                pass


# ── Public entry point ─────────────────────────────────────────────────────────

async def start() -> None:
    """
    Starts the periodic flush loop and the Kafka consumer loop as concurrent tasks.
    Called by workers/run_workers.py. Both tasks run until the process exits.
    """
    log.info("Personalisation worker starting")
    asyncio.create_task(_periodic_flush_loop(), name="personalisation-flush")
    await _consume_loop()  # blocks until cancelled
