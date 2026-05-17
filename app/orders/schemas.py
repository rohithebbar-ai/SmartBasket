import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.orders.models import OrderStatus


# ── Cart schemas ──────────────────────────────────────────────────────────────

class CartItem(BaseModel):
    """One line in the Redis cart hash. Price captured at add-to-cart time."""
    product_id: uuid.UUID
    name: str
    qty: int = Field(ge=1)
    unit_price: Decimal  # price at the moment this item was added / last updated


class AddToCartRequest(BaseModel):
    product_id: uuid.UUID
    qty: int = Field(default=1, ge=1)


class CartResponse(BaseModel):
    user_id: uuid.UUID
    items: list[CartItem]
    total: Decimal


# ── Order schemas ─────────────────────────────────────────────────────────────

class OrderItemSnapshot(BaseModel):
    """JSONB row inside orders.items — price is frozen at checkout time."""
    product_id: uuid.UUID
    name: str
    price_at_order: Decimal
    qty: int


class OrderCreate(BaseModel):
    """Body for POST /api/orders — user checks out their current cart."""
    pass  # no extra fields needed; cart is read from Redis by user_id


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    items: list[OrderItemSnapshot]
    total_amount: Decimal
    status: OrderStatus
    created_at: datetime
