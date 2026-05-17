import uuid
from datetime import datetime

from sqlalchemy import DateTime, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True, unique=True)

    # Written by the personalisation worker; never updated directly by the user via API.
    # Lists: ["Dell", "Apple"], ["laptop"], ["performance", "battery"]
    preferred_brands: Mapped[list] = mapped_column(JSONB, default=list)
    preferred_categories: Mapped[list] = mapped_column(JSONB, default=list)
    # Weighted dict: {"performance": 0.9, "battery": 0.6, "portability": 0.8}
    feature_priorities: Mapped[dict] = mapped_column(JSONB, default=dict)

    typical_price_min: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    typical_price_max: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
