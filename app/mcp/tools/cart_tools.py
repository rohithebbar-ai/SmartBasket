"""
Cart tools — read and write tools for the product discovery and cart flow.

Read tools (execute immediately, no await_confirmation gate):
  POST /check_stock_status          — current stock and price for a product
  POST /get_delivery_estimate       — delivery window based on stock level
  POST /get_frequently_bought_together — co-purchase products from order history

Write tools (always preceded by await_confirmation):
  POST /add_to_cart                 — add item to Redis cart, return updated total
"""

import uuid
import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.orders import service as order_service
from app.redis_client import get_redis_client

log = logging.getLogger(__name__)
router = APIRouter()

_DELIVERY_THRESHOLD = 10  # stock_count above which we promise 3-5 days


# ── Request / response models ─────────────────────────────────────────────────

class ProductIdBody(BaseModel):
    product_id: str

class FrequentlyBoughtBody(BaseModel):
    product_id: str
    limit: int = 3

class AddToCartBody(BaseModel):
    user_id: str
    product_id: str
    quantity: int = 1


# ── check_stock_status ────────────────────────────────────────────────────────

@router.post("/check_stock_status")
async def check_stock_status(body: ProductIdBody) -> dict:
    sql = text("""
        SELECT name, brand, CAST(current_price AS FLOAT) AS current_price, stock_count
        FROM products
        WHERE id = :product_id AND is_active = true
        LIMIT 1
    """)
    async with AsyncSessionLocal() as db:
        row = (await db.execute(sql, {"product_id": body.product_id})).mappings().first()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    stock = int(row["stock_count"])
    return {
        "in_stock": stock > 0,
        "stock_count": stock,
        "product_name": f"{row['brand']} {row['name']}",
        "current_price": row["current_price"],
    }


# ── get_delivery_estimate ─────────────────────────────────────────────────────

@router.post("/get_delivery_estimate")
async def get_delivery_estimate(body: ProductIdBody) -> dict:
    sql = text("SELECT stock_count FROM products WHERE id = :product_id AND is_active = true LIMIT 1")
    async with AsyncSessionLocal() as db:
        row = (await db.execute(sql, {"product_id": body.product_id})).mappings().first()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    stock = int(row["stock_count"])
    if stock == 0:
        return {"estimate": "out of stock", "stock_count": 0}
    if stock > _DELIVERY_THRESHOLD:
        return {"estimate": "3-5 business days", "stock_count": stock}
    return {"estimate": f"5-7 business days (only {stock} left)", "stock_count": stock}


# ── add_to_cart ───────────────────────────────────────────────────────────────

@router.post("/add_to_cart")
async def add_to_cart(body: AddToCartBody) -> dict:
    redis = await get_redis_client()
    async with AsyncSessionLocal() as db:
        cart = await order_service.add_to_cart(
            redis, db,
            user_id=uuid.UUID(body.user_id),
            product_id=uuid.UUID(body.product_id),
            qty=body.quantity,
        )

    # Find the item we just added for the confirmation message
    added = next(
        (i for i in cart.items if str(i.product_id) == body.product_id),
        None,
    )
    item_added = f"{added.name} × {added.qty}" if added else "item"

    return {
        "success": True,
        "item_added": item_added,
        "cart_total": float(cart.total),
    }


# ── get_frequently_bought_together ────────────────────────────────────────────

_CO_PURCHASE_SQL = text("""
    SELECT
        p.id,
        p.name,
        p.brand,
        CAST(p.current_price AS FLOAT) AS current_price,
        p.avg_rating,
        COUNT(*) AS co_count
    FROM orders o
    CROSS JOIN LATERAL jsonb_array_elements(o.items) AS item
    JOIN products p ON (item->>'product_id')::uuid = p.id
    WHERE o.id IN (
        SELECT DISTINCT o2.id
        FROM orders o2
        CROSS JOIN LATERAL jsonb_array_elements(o2.items) AS item2
        WHERE (item2->>'product_id')::uuid = :product_id
    )
      AND (item->>'product_id')::uuid != :product_id
      AND p.stock_count > 0
      AND p.is_active = true
    GROUP BY p.id, p.name, p.brand, p.current_price, p.avg_rating
    ORDER BY co_count DESC
    LIMIT :limit
""")

_CATEGORY_FALLBACK_SQL = text("""
    SELECT id, name, brand,
           CAST(current_price AS FLOAT) AS current_price,
           avg_rating
    FROM products
    WHERE category = :category
      AND id != :product_id
      AND stock_count > 0
      AND is_active = true
    ORDER BY avg_rating DESC
    LIMIT :limit
""")

_CATEGORY_SQL = text("SELECT category FROM products WHERE id = :product_id LIMIT 1")


@router.post("/get_frequently_bought_together")
async def get_frequently_bought_together(body: FrequentlyBoughtBody) -> dict:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                _CO_PURCHASE_SQL,
                {"product_id": body.product_id, "limit": body.limit},
            )
        ).mappings().all()

        if not rows:
            # Fallback: top-rated products in the same category
            cat_row = (
                await db.execute(_CATEGORY_SQL, {"product_id": body.product_id})
            ).mappings().first()

            category = cat_row["category"] if cat_row else None
            if category:
                rows = (
                    await db.execute(
                        _CATEGORY_FALLBACK_SQL,
                        {"category": category, "product_id": body.product_id, "limit": body.limit},
                    )
                ).mappings().all()

    products = [
        {
            "product_id": str(r["id"]),
            "name": f"{r['brand']} {r['name']}",
            "current_price": r["current_price"],
            "avg_rating": float(r["avg_rating"] or 0),
        }
        for r in rows
    ]
    return {"products": products}
