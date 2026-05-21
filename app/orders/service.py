import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.orders.models import Order, OrderStatus
from app.orders.schemas import CartItem, CartResponse, OrderItemSnapshot, OrderResponse
from app.products.models import Product

# Cart Redis key pattern: cart:{user_id}  — hash of product_id → JSON CartItem
# TTL: 7 days, refreshed on every write
_CART_TTL = 60 * 60 * 24 * 7


# ── Internal helpers ──────────────────────────────────────────────────────────

def _cart_key(user_id: uuid.UUID) -> str:
    return f"cart:{user_id}"


def _price_key(product_id: uuid.UUID) -> str:
    return f"current_price:{product_id}"


def _item_from_raw(raw: str) -> CartItem:
    return CartItem.model_validate(json.loads(raw))


async def _get_live_price(redis: Redis, db: AsyncSession, product_id: uuid.UUID) -> Decimal:
    """
    Returns the live unit price for a product.
    Redis is checked first (current_price:{product_id}, 10-min TTL set by pricing engine).
    Falls back to products.current_price in PostgreSQL if the key is absent or Redis is down.
    """
    try:
        cached = await redis.get(_price_key(product_id))
        if cached is not None:
            return Decimal(cached)
    except Exception:
        pass  # Redis unavailable — fall through to DB

    product = await db.scalar(select(Product).where(Product.id == product_id))
    if product is None:
        raise ValueError(f"Product {product_id} not found")
    return product.current_price


async def _get_product_name(db: AsyncSession, product_id: uuid.UUID) -> str:
    product = await db.scalar(
        select(Product.name).where(Product.id == product_id)
    )
    if product is None:
        raise ValueError(f"Product {product_id} not found")
    return product


# ── Cart operations ───────────────────────────────────────────────────────────

async def get_cart(redis: Redis, user_id: uuid.UUID) -> CartResponse:
    """Reads cart:{user_id} hash from Redis and computes the running total."""
    raw_items = await redis.hgetall(_cart_key(user_id))
    items = [_item_from_raw(v) for v in raw_items.values()]
    total = sum(i.unit_price * i.qty for i in items)
    return CartResponse(user_id=user_id, items=items, total=total)


async def add_to_cart(
    redis: Redis,
    db: AsyncSession,
    user_id: uuid.UUID,
    product_id: uuid.UUID,
    qty: int = 1,
) -> CartResponse:
    """
    Adds or increments a product in the cart.
    Price is read from Redis (current_price:{product_id}) first, DB second.
    The cart hash field key is the product_id string; value is a serialised CartItem.
    """
    price = await _get_live_price(redis, db, product_id)
    name  = await _get_product_name(db, product_id)

    key       = _cart_key(user_id)
    field     = str(product_id)
    existing  = await redis.hget(key, field)

    if existing:
        item = _item_from_raw(existing)
        item.qty       += qty
        item.unit_price = price  # refresh to latest live price
    else:
        item = CartItem(product_id=product_id, name=name, qty=qty, unit_price=price)

    await redis.hset(key, field, item.model_dump_json())
    await redis.expire(key, _CART_TTL)

    return await get_cart(redis, user_id)


async def remove_from_cart(
    redis: Redis,
    user_id: uuid.UUID,
    product_id: uuid.UUID,
) -> CartResponse:
    """Removes a product entirely from the cart hash."""
    await redis.hdel(_cart_key(user_id), str(product_id))
    return await get_cart(redis, user_id)


async def clear_cart(redis: Redis, user_id: uuid.UUID) -> None:
    """Deletes the entire cart key. Called after successful checkout."""
    await redis.delete(_cart_key(user_id))


# ── Order operations ──────────────────────────────────────────────────────────

async def create_order(
    redis: Redis,
    db: AsyncSession,
    user_id: uuid.UUID,
) -> OrderResponse:
    """
    Checks out the current cart:
      1. Reads cart from Redis — raises if empty
      2. Snapshots each item's price into the JSONB items column
      3. Inserts the Order row
      4. Clears the cart from Redis
    Kafka publish (order.created) is done in the router after this returns,
    so a Kafka failure never rolls back the committed order.
    """
    cart = await get_cart(redis, user_id)
    if not cart.items:
        raise ValueError("Cannot create order from an empty cart")

    snapshots = [
        OrderItemSnapshot(
            product_id=item.product_id,
            name=item.name,
            price_at_order=item.unit_price,
            qty=item.qty,
        )
        for item in cart.items
    ]

    order = Order(
        user_id=user_id,
        items=[s.model_dump(mode="json") for s in snapshots],
        total_amount=cart.total,
        status=OrderStatus.PENDING,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)

    await clear_cart(redis, user_id)

    return OrderResponse(
        id=order.id,
        user_id=order.user_id,
        items=snapshots,
        total_amount=order.total_amount,
        status=order.status,
        created_at=order.created_at,
    )


async def deliver_order(
    db: AsyncSession,
    order_id: uuid.UUID,
) -> Order:
    """
    Marks an order as delivered and records the delivery timestamp.
    Called by the admin PUT /orders/{order_id}/status endpoint, which simulates
    a courier webhook for the portfolio build.
    Returns the updated Order ORM row.
    Raises ValueError if the order does not exist.
    """
    now = datetime.now(timezone.utc)
    await db.execute(
        update(Order)
        .where(Order.id == order_id)
        .values(status=OrderStatus.DELIVERED, delivered_at=now)
    )
    await db.commit()

    order = await db.scalar(select(Order).where(Order.id == order_id))
    if order is None:
        raise ValueError(f"Order {order_id} not found")
    return order


async def get_order_by_id(
    db: AsyncSession,
    order_id: uuid.UUID,
    user_id: uuid.UUID,
) -> OrderResponse | None:
    """
    Returns an order by ID. user_id is checked so customers can only read their own orders.
    Returns None if not found or belongs to a different user.
    """
    order = await db.scalar(
        select(Order).where(Order.id == order_id, Order.user_id == user_id)
    )
    if order is None:
        return None

    snapshots = [OrderItemSnapshot.model_validate(item) for item in order.items]
    return OrderResponse(
        id=order.id,
        user_id=order.user_id,
        items=snapshots,
        total_amount=order.total_amount,
        status=order.status,
        created_at=order.created_at,
    )
