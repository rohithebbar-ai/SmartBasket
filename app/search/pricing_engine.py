"""
Pricing engine — background task that runs every PRICING_ENGINE_INTERVAL_SECONDS (120s).

Each cycle:
  1. Load all active products from PostgreSQL.
  2. Read views:{product_id} counters from Redis in one MGET round-trip.
  3. Compute category average views to normalise demand (Section 21.1 Phase A).
  4. Apply pricing rules — demand-score model with supply-constraint override.
  5. Clamp new price to [0.80, 1.30] × base_price.
  6. Write updated current_price to PostgreSQL + Redis cache (via products service).
  7. Publish price.updated to Kafka so the orders consumer can recalculate cart totals.

Pricing rule hierarchy (in priority order):
  1. Low stock + active demand  → +10% (supply scarcity premium)
  2. Demand-score model         → multiplier = 1 + 0.10 × (demand_score − 1)
     demand_score = views / avg_views_for_category
     > 1.0 → above-average demand → price up
     < 1.0 → below-average demand → price down (clearance)
  3. Near-average demand (±10%) → no change (avoid constant micro-updates)

The demand-score model supersedes the hard threshold rules from Section 11.2.
Section 21.1 Phase B (elasticity coefficients from price_history) can replace
ELASTICITY_COEF once 10+ pricing cycles have accumulated per product.

Runs as a background asyncio task started in app/main.py alongside Kafka consumers.
Never imported by the web server hot path — no circular import risk.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaConnectionError
from sqlalchemy import text

from app.config import settings
from app.database import AsyncSessionLocal
from app.products.models import PriceChangeReason
from app.products import service as product_service
from app.redis_client import get_redis_client

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

ELASTICITY_COEF = 0.10          # 10% price change per unit of demand-score deviation
_LOW_STOCK_THRESHOLD = 5        # stock_count ≤ this → supply-constraint rule fires
_LOW_STOCK_MIN_VIEWS = 30       # minimum views to confirm product is actively wanted
_DEMAND_DEADBAND = 0.10         # ±10% from category average → no action
_MIN_PRICE_CHANGE_PCT = 0.001   # skip update if change < 0.1% (avoids noise)

# ── Kafka producer singleton ──────────────────────────────────────────────────

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
    """Called during app shutdown — drains in-flight messages before stopping."""
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None


async def _publish_price_updated(
    product_id: str,
    old_price: float,
    new_price: float,
    reason: str,
) -> None:
    payload = {
        "event_type": "price.updated",
        "product_id": product_id,
        "old_price": old_price,
        "new_price": new_price,
        "change_percentage": round((new_price - old_price) / max(old_price, 0.01) * 100, 2),
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        producer = await _get_producer()
        await producer.send_and_wait(
            settings.kafka_topic_price_updated,
            value=payload,
            key=product_id,
        )
        log.debug("price.updated published: product_id=%s reason=%s", product_id, reason)
    except KafkaConnectionError:
        log.warning("Kafka unavailable — price.updated not published for %s", product_id)
    except Exception as exc:
        log.warning("Failed to publish price.updated for %s: %s", product_id, exc)


# ── Pricing logic ─────────────────────────────────────────────────────────────

def _compute_new_price(
    base_price: float,
    current_price: float,
    stock_count: int,
    views: int,
    avg_views_for_category: float,
) -> tuple[float, str] | tuple[None, None]:
    """
    Returns (new_price, reason) or (None, None) if no change is warranted.

    Priority:
      1. Out of stock  → skip (no price signal when product is unavailable)
      2. Low stock + active views → supply-constraint premium (+10%)
      3. Demand-score model → clip(1 + 0.10 × (demand_score − 1), min, max) × base_price
      4. Near-average demand (±10%) or negligible change → skip
    """
    if stock_count == 0:
        return None, None

    # Rule 1: Supply-constraint premium — stock is scarce and product is wanted
    if stock_count <= _LOW_STOCK_THRESHOLD and views >= _LOW_STOCK_MIN_VIEWS:
        multiplier = 1.10
        reason = PriceChangeReason.LOW_STOCK_HIGH_DEMAND.value
    else:
        # Rule 2: Demand-score model (Section 21.1 Phase A)
        demand_score = views / max(avg_views_for_category, 1.0)

        # Dead-band: ±10% from category average → no action
        if abs(demand_score - 1.0) <= _DEMAND_DEADBAND:
            return None, None

        multiplier = 1.0 + ELASTICITY_COEF * (demand_score - 1.0)
        reason = (
            PriceChangeReason.HIGH_DEMAND.value
            if demand_score > 1.0
            else PriceChangeReason.LOW_DEMAND_HIGH_STOCK.value
        )

    # Clamp: never below 80% or above 130% of base_price
    min_price = base_price * settings.pricing_min_multiplier
    max_price = base_price * settings.pricing_max_multiplier
    new_price = round(max(min_price, min(max_price, base_price * multiplier)), 2)

    # Skip if the change is too small to matter
    if abs(new_price - current_price) / max(current_price, 0.01) < _MIN_PRICE_CHANGE_PCT:
        return None, None

    return new_price, reason


# ── One pricing cycle ─────────────────────────────────────────────────────────

async def run_pricing_cycle() -> None:
    """
    Execute one full pricing cycle.
    Loads all products, reads Redis counters, applies rules, persists updates.
    """
    async with AsyncSessionLocal() as db:
        # Step 1: Load all active products
        result = await db.execute(text(
            "SELECT id, name, category, base_price, current_price, stock_count "
            "FROM products WHERE is_active = true"
        ))
        products = result.mappings().all()

    if not products:
        log.debug("Pricing cycle: no active products")
        return

    # Step 2: Read all view counters in one Redis MGET round-trip
    redis = get_redis_client()
    product_ids = [str(p["id"]) for p in products]
    view_values = await redis.mget(*[f"views:{pid}" for pid in product_ids])
    view_counts: dict[str, int] = {
        product_ids[i]: int(view_values[i]) if view_values[i] else 0
        for i in range(len(product_ids))
    }

    # Step 3: Compute per-category average views for demand-score normalisation
    category_views: dict[str, list[int]] = {}
    for p in products:
        category_views.setdefault(p["category"], []).append(
            view_counts.get(str(p["id"]), 0)
        )
    category_avg: dict[str, float] = {
        cat: sum(counts) / len(counts)
        for cat, counts in category_views.items()
    }

    # Step 4 & 5: Apply rules and persist updates
    updated = 0
    async with AsyncSessionLocal() as db:
        for p in products:
            pid = str(p["id"])
            views = view_counts.get(pid, 0)
            avg_views = category_avg.get(p["category"], 1.0)

            new_price_float, reason = _compute_new_price(
                base_price=float(p["base_price"]),
                current_price=float(p["current_price"]),
                stock_count=p["stock_count"],
                views=views,
                avg_views_for_category=avg_views,
            )

            if new_price_float is None:
                continue

            try:
                old_price = float(p["current_price"])
                await product_service.update_product_price(
                    db=db,
                    product_id=uuid.UUID(pid),
                    new_price=Decimal(str(new_price_float)),
                    reason=PriceChangeReason(reason),
                )
                await _publish_price_updated(pid, old_price, new_price_float, reason)
                updated += 1
                log.info(
                    "Price updated: %s  %.2f → %.2f  reason=%s",
                    p["name"], old_price, new_price_float, reason,
                )
            except Exception as exc:
                log.error("Failed to update price for product %s: %s", pid, exc)

    log.info("Pricing cycle complete: %d/%d products updated", updated, len(products))


# ── Background task loop ──────────────────────────────────────────────────────

_pricing_task: asyncio.Task | None = None


async def _pricing_loop() -> None:
    """
    Infinite loop — runs one cycle then sleeps for PRICING_ENGINE_INTERVAL_SECONDS.
    Exits cleanly on CancelledError (app shutdown).
    """
    log.info(
        "Pricing engine started — cycle every %ds",
        settings.pricing_engine_interval_seconds,
    )
    while True:
        try:
            await run_pricing_cycle()
        except asyncio.CancelledError:
            break
        except Exception:
            log.error("Pricing cycle raised an unhandled exception", exc_info=True)

        try:
            await asyncio.sleep(settings.pricing_engine_interval_seconds)
        except asyncio.CancelledError:
            break

    log.info("Pricing engine stopped")


async def start_pricing_engine() -> None:
    """Spawn the pricing loop as a background asyncio task."""
    global _pricing_task
    _pricing_task = asyncio.create_task(_pricing_loop(), name="pricing-engine")
    log.info("Pricing engine task created")


async def stop_pricing_engine() -> None:
    """Cancel the loop and wait for it to finish cleanly."""
    global _pricing_task
    if _pricing_task and not _pricing_task.done():
        _pricing_task.cancel()
        try:
            await _pricing_task
        except asyncio.CancelledError:
            pass
        _pricing_task = None
    await close_producer()
    log.info("Pricing engine stopped")
