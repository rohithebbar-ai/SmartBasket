import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, Float, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.expression import text

from app.database import Base


class PriceChangeReason(str, enum.Enum):
    HIGH_DEMAND = "high_demand"
    LOW_STOCK_HIGH_DEMAND = "low_stock_high_demand"
    HIGH_ABANDONMENT = "high_abandonment"
    LOW_DEMAND_HIGH_STOCK = "low_demand_high_stock"


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    brand: Mapped[str] = mapped_column(String, nullable=False, index=True)
    category: Mapped[str] = mapped_column(String, nullable=False, index=True)
    base_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    current_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # specs JSONB: processor, ram_gb, storage_gb, display_*, gpu, use_cases, etc.
    specs: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    stock_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_rating: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # ── Fashion / H&M columns (migration 017) ────────────────────────────────
    external_product_id: Mapped[str | None]  = mapped_column(String, unique=True, index=True)
    description:         Mapped[str | None]  = mapped_column(Text)
    image_url:           Mapped[str | None]  = mapped_column(Text)
    attributes:          Mapped[dict]        = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    embedding_status:    Mapped[str]         = mapped_column(String, nullable=False, default="pending")
    last_ingested_at:    Mapped[datetime | None] = mapped_column()

    # Fashion sentiment (migration 017) — NULL until sentiment worker runs
    style_sentiment:       Mapped[float | None] = mapped_column(Float)
    quality_sentiment:     Mapped[float | None] = mapped_column(Float)
    fit_sentiment:         Mapped[float | None] = mapped_column(Float)
    comfort_sentiment:     Mapped[float | None] = mapped_column(Float)
    versatility_sentiment: Mapped[float | None] = mapped_column(Float)
    delivery_sentiment:    Mapped[float | None] = mapped_column(Float)

    # Electronics sentiment (migration 013) — NULL for fashion products
    battery_sentiment:       Mapped[float | None] = mapped_column(Float)
    display_sentiment:       Mapped[float | None] = mapped_column(Float)
    build_quality_sentiment: Mapped[float | None] = mapped_column(Float)
    value_sentiment:         Mapped[float | None] = mapped_column(Float)
    performance_sentiment:   Mapped[float | None] = mapped_column(Float)
    keyboard_sentiment:      Mapped[float | None] = mapped_column(Float)
    thermal_sentiment:       Mapped[float | None] = mapped_column(Float)
    top_complaint:           Mapped[str | None]   = mapped_column(Text)
    top_praise:              Mapped[str | None]   = mapped_column(Text)
    sentiment_scored_at:     Mapped[datetime | None] = mapped_column()

    reviews: Mapped[list["Review"]] = relationship(
        "Review",
        back_populates="product",
        lazy="noload",
        cascade="all, delete-orphan",
    )
    price_history: Mapped[list["PriceHistory"]] = relationship(
        "PriceHistory",
        back_populates="product",
        lazy="noload",
        cascade="all, delete-orphan",
        order_by="PriceHistory.changed_at.desc()",
    )


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    review_text: Mapped[str | None] = mapped_column(Text)
    # Aspect sentiment scores — NULL until run_sentiment.py populates them.
    battery_sentiment: Mapped[float | None] = mapped_column(Float)
    display_sentiment: Mapped[float | None] = mapped_column(Float)
    build_quality_sentiment: Mapped[float | None] = mapped_column(Float)
    value_sentiment: Mapped[float | None] = mapped_column(Float)
    performance_sentiment: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    product: Mapped["Product"] = relationship(
        "Product", back_populates="reviews", lazy="noload"
    )


class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    old_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    new_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    change_percentage: Mapped[float] = mapped_column(Float, nullable=False)
    # native_enum=False → stored as VARCHAR, matching the migration's CHECK constraint.
    # values_callable forces SQLAlchemy to store .value (lowercase) not .name (uppercase).
    # Python 3.11 changed str(StrEnum) behaviour; without this it inserts the .name.
    reason: Mapped[PriceChangeReason] = mapped_column(
        SAEnum(
            PriceChangeReason,
            name="price_change_reason",
            native_enum=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    changed_at: Mapped[datetime] = mapped_column(server_default=func.now())

    product: Mapped["Product"] = relationship(
        "Product", back_populates="price_history", lazy="noload"
    )
