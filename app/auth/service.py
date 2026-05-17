import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.schemas import UserCreate
from app.auth.utils import hash_password, verify_password

# Pre-computed bcrypt hash used for constant-time comparison when the user is not found.
# Prevents timing attacks where an attacker distinguishes "email not found" from "wrong
# password" by measuring response time differences.
_DUMMY_HASH = "$2b$12$EixZaYVKX30e4RqLJdQnDuv5MSaGMleDO8kT8k6jYaTZ8hZ5B1gZC"


async def create_user(db: AsyncSession, data: UserCreate) -> User:
    """
    Register a new user.
    
    Raises 400 if the email is already registered.
    Never stores the plain text password — only the bcrypt hash.
    """
    # check if email already exists
    existing = await db.scalar(select(User).where(User.email == data.email))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = User(email=data.email, hashed_password=hash_password(data.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User:
    """
    Verify credentials and return the user if valid.
    Raises 401 if email not found or password is wrong.
    Note: we return the same error for both cases intentionally —
    telling an attacker "email not found" helps them enumerate valid emails.
    """
    user = await db.scalar(select(User).where(User.email == email))
    # Always run verify_password even when user is None to prevent timing attacks.
    password_ok = verify_password(password, user.hashed_password if user else _DUMMY_HASH)
    if not user or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.scalar(select(User).where(User.id == user_id))
