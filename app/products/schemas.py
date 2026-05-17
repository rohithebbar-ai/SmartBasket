import uuid
from datetime import datetime
from decimal import Decimal
from math import ceil

from pydantic import BaseModel, ConfigDict, Field


# ── Filters ───────────────────────────────────────────────────────────────────

class ProductFilters(BaseModel):
    """Query parameters for the product list endpoint."""
    brand: str | None = None
    category: str | None = None
    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)
    min_rating: float | None = Field(default=None, ge=0.0, le=5.0)
    in_stock: bool | None = None  # True → stock_count > 0


# ── Request schemas ───────────────────────────────────────────────────────────

class ProductCreate(BaseModel):
    """Admin input for POST /api/products. base_price and current_price must be > 0."""
    name: str = Field(min_length=1, max_length=500)
    brand: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    base_price: Decimal = Field(gt=0, decimal_places=2)
    current_price: Decimal = Field(gt=0, decimal_places=2)
    specs: dict = Field(default_factory=dict)
    stock_count: int = Field(default=0, ge=0)


class ProductPriceUpdate(BaseModel):
    """Payload for PATCH /api/products/{id}/price. Used by the pricing engine."""
    new_price: Decimal = Field(gt=0, decimal_places=2)
    reason: str | None = None  # pricing engine passes the PriceChangeReason string


# ── Response schemas ──────────────────────────────────────────────────────────

class ReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    rating: int
    review_text: str | None
    battery_sentiment: float | None
    display_sentiment: float | None
    build_quality_sentiment: float | None
    value_sentiment: float | None
    performance_sentiment: float | None
    created_at: datetime


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    brand: str
    category: str
    base_price: Decimal
    # current_price: reflects the live dynamic price. The service overlays the
    # Redis-cached price on top of the DB value when available.
    current_price: Decimal
    specs: dict
    stock_count: int
    avg_rating: float
    is_active: bool
    created_at: datetime


class ProductDetailResponse(ProductResponse):
    """Single-product response that includes the review list."""
    reviews: list[ReviewResponse] = Field(default_factory=list)


class ProductListResponse(BaseModel):
    items: list[ProductResponse]
    total: int
    page: int
    limit: int
    pages: int

    @classmethod
    def build(
        cls,
        items: list[ProductResponse],
        total: int,
        page: int,
        limit: int,
    ) -> "ProductListResponse":
        return cls(
            items=items,
            total=total,
            page=page,
            limit=limit,
            pages=ceil(total / limit) if limit else 1,
        )
