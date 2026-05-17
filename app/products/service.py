import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.products.kafka import publish_product_created, publish_product_viewed
from app.products.models import PriceHistory, PriceChangeReason, Product, Review
from app.products.schemas import (
    ProductCreate,
    ProductFilters,
    ProductListResponse,
    ProductResponse,
)
from app.redis_client import get_redis_client


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_conditions(filters: ProductFilters) -> list:
    """Returns a list of SQLAlchemy WHERE conditions from a ProductFilters object."""
    conds = [Product.is_active == True]  # noqa: E712 — SQLAlchemy requires == not is
    if filters.brand:
        conds.append(Product.brand == filters.brand)
    if filters.category:
        conds.append(Product.category == filters.category)
    if filters.min_price is not None:
        conds.append(Product.current_price >= filters.min_price)
    if filters.max_price is not None:
        conds.append(Product.current_price <= filters.max_price)
    if filters.min_rating is not None:
        conds.append(Product.avg_rating >= filters.min_rating)
    if filters.in_stock is True:
        conds.append(Product.stock_count > 0)
    return conds


async def _overlay_redis_price(product: Product) -> Product:
    """
    Checks Redis for a live price override and mutates product.current_price in place.
    Falls back to the DB value silently if Redis is unavailable or the key is absent.
    """
    try:
        redis = get_redis_client()
        cached = await redis.get(f"current_price:{product.id}")
        if cached is not None:
            product.current_price = Decimal(cached)
    except Exception:
        pass  # Redis miss or connection error — DB price is authoritative fallback
    return product


# ── Public service functions ──────────────────────────────────────────────────

async def get_products(
    db: AsyncSession,
    filters: ProductFilters,
    page: int = 1,
    limit: int = 20,
) -> ProductListResponse:
    """
    Returns a paginated, filtered product list.
    Builds the filter conditions once and reuses them for both count and data queries.
    Redis price overlay is applied to each returned product.
    """
    conds = _build_conditions(filters)
    offset = (page - 1) * limit

    total: int = await db.scalar(
        select(func.count()).select_from(Product).where(*conds)
    ) or 0

    result = await db.scalars(
        select(Product)
        .where(*conds)
        .order_by(Product.avg_rating.desc(), Product.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    products = list(result.all())

    for p in products:
        await _overlay_redis_price(p)

    return ProductListResponse.build(
        items=[ProductResponse.model_validate(p) for p in products],
        total=total,
        page=page,
        limit=limit,
    )


async def get_product_by_id(
    db: AsyncSession, product_id: uuid.UUID
) -> Product | None:
    """
    Returns a single active product with its reviews eagerly loaded via selectinload.
    Applies Redis price overlay before returning.
    Returns None if the product does not exist or is inactive.
    """
    product = await db.scalar(
        select(Product)
        .options(selectinload(Product.reviews))
        .where(Product.id == product_id, Product.is_active == True)  # noqa: E712
    )
    if product is None:
        return None
    await _overlay_redis_price(product)
    # Fire-and-don't-fail: Kafka unavailability must not break product page loads.
    await publish_product_viewed(product_id=product.id)
    return product


async def create_product(db: AsyncSession, data: ProductCreate) -> Product:
    """Inserts a new product row. avg_rating starts at 0.0 — updated by the review pipeline."""
    product = Product(**data.model_dump())
    db.add(product)
    await db.commit()
    await db.refresh(product)
    await publish_product_created(product_id=product.id)
    return product


async def update_product_price(
    db: AsyncSession,
    product_id: uuid.UUID,
    new_price: Decimal,
    reason: PriceChangeReason | None = None,
) -> Product | None:
    """
    Updates current_price in PostgreSQL and writes the new price to the Redis cache.
    If reason is provided, also appends a price_history row for audit.
    Returns None if the product does not exist.
    """
    product = await db.scalar(
        select(Product).where(Product.id == product_id)
    )
    if product is None:
        return None

    old_price = product.current_price
    product.current_price = new_price

    if reason is not None:
        change_pct = float((new_price - old_price) / old_price * 100)
        db.add(PriceHistory(
            product_id=product_id,
            old_price=old_price,
            new_price=new_price,
            change_percentage=round(change_pct, 4),
            reason=reason,
        ))

    await db.commit()
    await db.refresh(product)

    # Write-through cache: pricing engine reads from Redis for speed.
    try:
        redis = get_redis_client()
        await redis.set(f"current_price:{product_id}", str(new_price), ex=600)
    except Exception:
        pass  # Cache miss is acceptable — DB is the source of truth

    return product


async def get_product_reviews(
    db: AsyncSession, product_id: uuid.UUID
) -> list[Review]:
    """
    Returns all reviews for a product, ordered newest first.
    Does not check is_active — reviews for inactive products are still readable
    by admin analytics queries.
    """
    result = await db.scalars(
        select(Review)
        .where(Review.product_id == product_id)
        .order_by(Review.created_at.desc())
    )
    return list(result.all())
