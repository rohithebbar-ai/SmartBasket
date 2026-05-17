import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User, UserRole
from app.auth.service import get_user_by_id
from app.auth.utils import decode_access_token
from app.database import get_db as get_session

_bearer = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_session),
) -> User:
    """
    Reads Bearer token, verifies signature and expiry, returns the User.
    Raises HTTP 401 on any failure.
    Import this in any route that requires authentication.
    """
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(payload["user_id"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await get_user_by_id(db, user_id)


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    Wraps get_current_user and additionally checks role == admin.
    Raises HTTP 403 if the authenticated user is not an admin.
    Import this in admin-only routes (analytics, stock updates, bulk notifications).
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user
