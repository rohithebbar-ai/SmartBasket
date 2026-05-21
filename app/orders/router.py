import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_admin
from app.auth.models import User, UserRole
from app.database import get_db
from app.orders import service
from app.orders.kafka_producer import (
    publish_cart_updated,
    publish_order_created,
    publish_order_delivered,
)
from app.orders.schemas import AddToCartRequest, CartResponse, OrderResponse
from app.redis_client import get_redis

router = APIRouter()


# ── Cart ──────────────────────────────────────────────────────────────────────

@router.post("/cart/add", response_model=CartResponse)
async def add_to_cart(
    data: AddToCartRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> CartResponse:
    try:
        cart = await service.add_to_cart(redis, db, current_user.id, data.product_id, data.qty)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    await publish_cart_updated(current_user.id, cart.total)
    return cart


@router.delete("/cart/remove", response_model=CartResponse)
async def remove_from_cart(
    product_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
) -> CartResponse:
    cart = await service.remove_from_cart(redis, current_user.id, product_id)
    await publish_cart_updated(current_user.id, cart.total)
    return cart


@router.get("/cart/{user_id}", response_model=CartResponse)
async def get_cart(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
) -> CartResponse:
    if current_user.id != user_id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access another user's cart")
    return await service.get_cart(redis, user_id)


# ── Orders ────────────────────────────────────────────────────────────────────

@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> OrderResponse:
    try:
        order = await service.create_order(redis, db, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    await publish_order_created(
        order_id=order.id,
        user_id=order.user_id,
        items=[i.model_dump(mode="json") for i in order.items],
        total_amount=order.total_amount,
    )
    return order


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    order = await service.get_order_by_id(db, order_id, current_user.id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


class _UpdateStatusBody(BaseModel):
    status: Literal["delivered"]


@router.put("/{order_id}/status")
async def update_order_status(
    order_id: uuid.UUID,
    body: _UpdateStatusBody,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Admin-only. Simulates a courier webhook confirming delivery.
    Marks the order delivered, records delivered_at, and publishes order.delivered
    to Kafka so the post-purchase worker can schedule the review reminder.
    Only 'delivered' is accepted — other status transitions are out of scope.
    """
    try:
        order = await service.deliver_order(db, order_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    product_ids = [str(i["product_id"]) for i in (order.items or [])]
    await publish_order_delivered(
        order_id=str(order.id),
        user_id=str(order.user_id),
        product_ids=product_ids,
    )

    return {
        "order_id": str(order.id),
        "status": order.status,
        "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
    }
