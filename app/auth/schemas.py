import uuid

from pydantic import BaseModel, EmailStr, field_validator

from app.auth.models import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        """
        Enforce minimum password requirements.
        
        We do not store the password — only the hash.
        But we validate before hashing to give clear error messages.
        """
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UserLogin(BaseModel):
    """The client sends what to log in"""
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """What we send back - never includes the hashed password"""
    id: uuid.UUID
    email: EmailStr
    role: UserRole
    is_active: bool

    model_config = {"from_attributes": True}  # allows creating from SQLAlchemy model


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer" # standard OAuth2 token type
    user: UserResponse  # convenience - client gets user info without extra request
