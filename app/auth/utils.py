from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def create_access_token(user_id: str, role: str, expiry_hours: int | None = None) -> str:
    hours = expiry_hours if expiry_hours is not None else settings.jwt_expiry_hours
    expire = datetime.now(timezone.utc) + timedelta(hours=hours)
    payload = {"user_id": user_id, "role": role, "exp": expire}
    return jwt.encode(payload, settings.app_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Raises JWTError on invalid or expired token."""
    return jwt.decode(token, settings.app_secret_key, algorithms=[settings.jwt_algorithm])
