import uuid
from decimal import Decimal

from pydantic import BaseModel, Field


class UserPreferencesResponse(BaseModel):
    user_id: uuid.UUID
    preferred_brands: list[str] = Field(default_factory=list)
    preferred_categories: list[str] = Field(default_factory=list)
    feature_priorities: dict[str, float] = Field(default_factory=dict)
    typical_price_min: Decimal | None = None
    typical_price_max: Decimal | None = None

    model_config = {"from_attributes": True}


class UserPreferencesUpdate(BaseModel):
    """Partial update — only supplied fields are written; omitted fields are left unchanged."""
    preferred_brands: list[str] | None = None
    preferred_categories: list[str] | None = None
    feature_priorities: dict[str, float] | None = None
    typical_price_min: Decimal | None = None
    typical_price_max: Decimal | None = None
