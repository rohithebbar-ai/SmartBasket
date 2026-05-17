from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.auth.schemas import Token, UserCreate, UserLogin, UserResponse
from app.auth.service import authenticate_user, create_user
from app.auth.utils import create_access_token
from app.database import get_db as get_session

router = APIRouter()


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(data: UserCreate, db: AsyncSession = Depends(get_session)) -> User:
    return await create_user(db, data)


@router.post("/login", response_model=Token)
async def login(data: UserLogin, db: AsyncSession = Depends(get_session)) -> Token:
    user = await authenticate_user(db, data.email, data.password)
    token = create_access_token(str(user.id), user.role.value)
    return Token(access_token=token)


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
