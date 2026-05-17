"""
Auth module tests — register, login, JWT token, protected routes, admin guard.

Strategy: patch service functions at the router/dependency boundary so no
real DB is needed. JWT encoding/decoding uses the real jose library and the
real APP_SECRET_KEY from settings so token-level tests exercise genuine behaviour.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from jose import jwt

from app.auth.models import User, UserRole
from app.auth.utils import create_access_token, hash_password, verify_password
from app.config import settings
from app.database import get_db
from app.main import create_app

# ── Shared test data ───────────────────────────────────────────────────────────

USER_ID    = uuid.uuid4()
USER_EMAIL = "test@shopsense.com"
USER_PASS  = "password123"


def _make_user(role: UserRole = UserRole.CUSTOMER) -> User:
    user         = MagicMock(spec=User)
    user.id      = USER_ID
    user.email   = USER_EMAIL
    user.role    = role
    user.is_active = True
    return user


def _make_client() -> TestClient:
    """App with DB dependency stubbed out — no PostgreSQL required."""
    app = create_app()

    async def _stub_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _stub_db
    return TestClient(app, raise_server_exceptions=True)


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _valid_token(role: UserRole = UserRole.CUSTOMER) -> str:
    return create_access_token(str(USER_ID), role.value)


def _expired_token() -> str:
    payload = {
        "sub":  str(USER_ID),
        "role": "customer",
        "iat":  datetime.now(timezone.utc) - timedelta(hours=2),
        "exp":  datetime.now(timezone.utc) - timedelta(hours=1),
    }
    return jwt.encode(payload, settings.app_secret_key, algorithm=settings.jwt_algorithm)


# ── POST /auth/register ────────────────────────────────────────────────────────

class TestRegister:
    def test_success_returns_201_with_user_shape(self):
        client = _make_client()
        with patch("app.auth.router.create_user", new=AsyncMock(return_value=_make_user())):
            resp = client.post("/auth/register", json={"email": USER_EMAIL, "password": USER_PASS})

        assert resp.status_code == 201
        body = resp.json()
        assert body["email"]  == USER_EMAIL
        assert body["role"]   == "customer"
        assert body["id"]     == str(USER_ID)

    def test_hashed_password_never_appears_in_response(self):
        client = _make_client()
        with patch("app.auth.router.create_user", new=AsyncMock(return_value=_make_user())):
            resp = client.post("/auth/register", json={"email": USER_EMAIL, "password": USER_PASS})

        body_str = resp.text
        assert "hashed_password" not in body_str
        assert USER_PASS not in body_str

    def test_duplicate_email_returns_409(self):
        client = _make_client()
        with patch(
            "app.auth.router.create_user",
            new=AsyncMock(side_effect=HTTPException(status.HTTP_409_CONFLICT, "Email already registered")),
        ):
            resp = client.post("/auth/register", json={"email": USER_EMAIL, "password": USER_PASS})

        assert resp.status_code == 409
        assert "already registered" in resp.json()["detail"]

    def test_password_shorter_than_8_chars_returns_422(self):
        client = _make_client()
        resp = client.post("/auth/register", json={"email": USER_EMAIL, "password": "short"})
        assert resp.status_code == 422

    def test_invalid_email_format_returns_422(self):
        client = _make_client()
        resp = client.post("/auth/register", json={"email": "not-an-email", "password": USER_PASS})
        assert resp.status_code == 422

    def test_missing_fields_returns_422(self):
        client = _make_client()
        assert client.post("/auth/register", json={"email": USER_EMAIL}).status_code == 422
        assert client.post("/auth/register", json={"password": USER_PASS}).status_code == 422


# ── POST /auth/login ───────────────────────────────────────────────────────────

class TestLogin:
    def test_valid_credentials_return_token_and_user(self):
        client = _make_client()
        with patch("app.auth.router.authenticate_user", new=AsyncMock(return_value=_make_user())):
            resp = client.post("/auth/login", json={"email": USER_EMAIL, "password": USER_PASS})

        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["user"]["email"] == USER_EMAIL
        assert body["user"]["role"]  == "customer"

    def test_token_payload_contains_user_id_role_exp(self):
        client = _make_client()
        with patch("app.auth.router.authenticate_user", new=AsyncMock(return_value=_make_user())):
            resp = client.post("/auth/login", json={"email": USER_EMAIL, "password": USER_PASS})

        token   = resp.json()["access_token"]
        payload = jwt.decode(token, settings.app_secret_key, algorithms=[settings.jwt_algorithm])
        assert payload["sub"]  == str(USER_ID)
        assert payload["role"] == "customer"
        assert "exp" in payload
        assert "iat" in payload

    def test_token_payload_never_contains_sensitive_fields(self):
        client = _make_client()
        with patch("app.auth.router.authenticate_user", new=AsyncMock(return_value=_make_user())):
            resp = client.post("/auth/login", json={"email": USER_EMAIL, "password": USER_PASS})

        token   = resp.json()["access_token"]
        payload = jwt.decode(token, settings.app_secret_key, algorithms=[settings.jwt_algorithm])
        assert "hashed_password" not in payload
        assert "email" not in payload   # JWT contains only user_id + role, not PII

    def test_wrong_password_returns_401(self):
        client = _make_client()
        with patch(
            "app.auth.router.authenticate_user",
            new=AsyncMock(side_effect=HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")),
        ):
            resp = client.post("/auth/login", json={"email": USER_EMAIL, "password": "wrongpassword"})

        assert resp.status_code == 401
        assert "Incorrect" in resp.json()["detail"]

    def test_login_response_never_contains_password_field(self):
        client = _make_client()
        with patch("app.auth.router.authenticate_user", new=AsyncMock(return_value=_make_user())):
            resp = client.post("/auth/login", json={"email": USER_EMAIL, "password": USER_PASS})

        assert "hashed_password" not in resp.text
        assert "password" not in resp.json().get("user", {})


# ── GET /auth/me ───────────────────────────────────────────────────────────────

class TestGetMe:
    def test_valid_token_returns_current_user(self):
        client = _make_client()
        with patch("app.auth.dependencies.get_user_by_id", new=AsyncMock(return_value=_make_user())):
            resp = client.get("/auth/me", headers=_auth_header(_valid_token()))

        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == USER_EMAIL
        assert body["id"]    == str(USER_ID)

    def test_expired_token_returns_401(self):
        client = _make_client()
        resp = client.get("/auth/me", headers=_auth_header(_expired_token()))
        assert resp.status_code == 401

    def test_tampered_signature_returns_401(self):
        client = _make_client()
        token   = _valid_token()
        tampered = token[:-6] + "XXXXXX"   # corrupt last 6 chars of the signature
        resp = client.get("/auth/me", headers=_auth_header(tampered))
        assert resp.status_code == 401

    def test_token_signed_with_wrong_key_returns_401(self):
        client = _make_client()
        payload = {"sub": str(USER_ID), "role": "customer",
                   "exp": datetime.now(timezone.utc) + timedelta(hours=1)}
        token = jwt.encode(payload, "completely-wrong-secret-key-32ch", algorithm="HS256")
        resp = client.get("/auth/me", headers=_auth_header(token))
        assert resp.status_code == 401

    def test_no_token_returns_401(self):
        client = _make_client()
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_wrong_auth_scheme_returns_401(self):
        # auto_error=False on HTTPBearer means wrong scheme → credentials=None → our 401
        client = _make_client()
        resp = client.get("/auth/me", headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert resp.status_code == 401


# ── Admin guard ────────────────────────────────────────────────────────────────

class TestAdminGuard:
    def test_customer_on_admin_route_returns_403(self):
        """
        POST /api/products/ requires require_admin.
        get_current_user succeeds (valid token, real user returned by mock),
        then require_admin sees role=CUSTOMER and raises 403.
        """
        client = _make_client()
        with patch(
            "app.auth.dependencies.get_user_by_id",
            new=AsyncMock(return_value=_make_user(role=UserRole.CUSTOMER)),
        ):
            resp = client.post(
                "/api/products/",
                headers=_auth_header(_valid_token(role=UserRole.CUSTOMER)),
                json={"name": "Test Laptop", "brand": "Dell", "price": 50000},
            )

        assert resp.status_code == 403
        assert "Admin" in resp.json()["detail"]

    def test_admin_token_has_admin_role_in_payload(self):
        token   = create_access_token(str(USER_ID), UserRole.ADMIN.value)
        payload = jwt.decode(token, settings.app_secret_key, algorithms=[settings.jwt_algorithm])
        assert payload["role"] == "admin"


# ── Unit: bcrypt hash / verify ─────────────────────────────────────────────────

class TestPasswordHashing:
    def test_hash_differs_from_plain(self):
        hashed = hash_password(USER_PASS)
        assert hashed != USER_PASS

    def test_two_hashes_of_same_password_differ(self):
        # bcrypt includes a random salt — same input produces different hashes
        assert hash_password(USER_PASS) != hash_password(USER_PASS)

    def test_verify_correct_password_returns_true(self):
        hashed = hash_password(USER_PASS)
        assert verify_password(USER_PASS, hashed) is True

    def test_verify_wrong_password_returns_false(self):
        hashed = hash_password(USER_PASS)
        assert verify_password("wrongpassword", hashed) is False
