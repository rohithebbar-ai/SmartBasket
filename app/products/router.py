import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_admin
from app.auth.models import User
from app.database import get_db
from app.products import service
from app.products.models import PriceChangeReason
from app.products.schemas import (
    ProductCreate,
    ProductDetailResponse,
    ProductFilters,
    ProductListResponse,
    ProductPriceUpdate,
    ProductResponse,
    ReviewResponse,
)

router = APIRouter()


@router.get("/", response_model=ProductListResponse)
async def list_products(
    filters: ProductFilters = Depends(),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> ProductListResponse:
    """Paginated product list. Prices are overlaid from Redis when available."""
    return await service.get_products(db, filters, page, limit)


@router.get("/{product_id}", response_model=ProductDetailResponse)
async def get_product(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ProductDetailResponse:
    """
    Single product with reviews. Publishes product.viewed Kafka event (Day 6 —
    Kafka producer not yet wired; event skipped until then).
    """
    product = await service.get_product_by_id(db, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return ProductDetailResponse.model_validate(product)


@router.post("/", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    data: ProductCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> ProductResponse:
    """Admin only. Inserts the product row. Embedding generation is triggered separately."""
    product = await service.create_product(db, data)
    return ProductResponse.model_validate(product)


@router.patch("/{product_id}/price", response_model=ProductResponse)
async def update_price(
    product_id: uuid.UUID,
    data: ProductPriceUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> ProductResponse:
    """
    Updates current_price in PostgreSQL and the Redis cache.
    Called by the pricing engine (Day 15). Protected by require_admin until
    a dedicated internal service token is introduced.
    """
    reason = PriceChangeReason(data.reason) if data.reason else None
    product = await service.update_product_price(db, product_id, data.new_price, reason)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return ProductResponse.model_validate(product)


@router.get("/{product_id}/reviews", response_model=list[ReviewResponse])
async def get_reviews(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[ReviewResponse]:
    """All reviews for a product, ordered newest first."""
    reviews = await service.get_product_reviews(db, product_id)
    return [ReviewResponse.model_validate(r) for r in reviews]
