import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import UserPreferences
from app.users.schemas import UserPreferencesUpdate


async def get_preferences(db: AsyncSession, user_id: uuid.UUID) -> UserPreferences | None:
    return await db.scalar(select(UserPreferences).where(UserPreferences.user_id == user_id))


async def upsert_preferences(
    db: AsyncSession, user_id: uuid.UUID, data: UserPreferencesUpdate
) -> UserPreferences:
    prefs = await db.scalar(select(UserPreferences).where(UserPreferences.user_id == user_id))
    updates = data.model_dump(exclude_none=True)
    if prefs is None:
        prefs = UserPreferences(user_id=user_id, **updates)
        db.add(prefs)
    else:
        for field, value in updates.items():
            setattr(prefs, field, value)
    await db.commit()
    await db.refresh(prefs)
    return prefs
