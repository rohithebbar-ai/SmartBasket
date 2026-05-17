from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.database import get_db
from app.users import service
from app.users.schemas import UserPreferencesResponse, UserPreferencesUpdate

router = APIRouter()


@router.get("/me/preferences", response_model=UserPreferencesResponse)
async def get_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserPreferencesResponse:
    prefs = await service.get_preferences(db, current_user.id)
    if prefs is None:
        return UserPreferencesResponse(user_id=current_user.id)
    return UserPreferencesResponse.model_validate(prefs)


@router.put("/me/preferences", response_model=UserPreferencesResponse)
async def update_preferences(
    data: UserPreferencesUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserPreferencesResponse:
    prefs = await service.upsert_preferences(db, current_user.id, data)
    return UserPreferencesResponse.model_validate(prefs)
