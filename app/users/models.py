import uuid
from datetime import datetime

from sqlalchemy import DateTime, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# The User model lives in app/auth/models.py (Section 20.5).
# This module owns only the UserPreferences table, which is written by
# the personalisation worker and read by the agent module.


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    # Written by personalisation worker; never updated directly by user
    preferred_brands: Mapped[dict] = mapped_column(JSONB, default=list)
    preferred_categories: Mapped[dict] = mapped_column(JSONB, default=list)
    typical_price_min: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    typical_price_max: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    feature_priorities: Mapped[dict] = mapped_column(JSONB, default=dict)

    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
