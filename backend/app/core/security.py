"""
app/core/security.py

Authentication and authorization primitives:
  - Password hashing/verification (passlib, bcrypt)
  - JWT access/refresh token creation and decoding (python-jose)
  - FastAPI dependencies: get_current_user, require_roles

Every protected route in the codebase depends on get_current_user (and,
for write endpoints restricted to admin/analyst, require_roles). This
file is intentionally the only place JWT/password logic lives — routes
and services never touch passlib/jose directly.

Depends on (generated in an upcoming file):
  - app.db.repositories.users_repo : get_by_id
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from motor.motor_asyncio import AsyncIOMotorDatabase
from passlib.context import CryptContext

from app.config import settings
from app.core.exceptions import AppError
from app.db.database import get_database
from app.models.user import UserModel, UserRole

logger = logging.getLogger(__name__)

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# FastAPI's HTTPBearer parses the `Authorization: Bearer <jwt>` header for
# us and raises its own 403 on a missing header — we normalize that into
# our standard AppError shape inside get_current_user below, so callers
# always see a consistent 401 UNAUTHORIZED envelope regardless of whether
# the header was missing, malformed, or the token itself was invalid.
_bearer_scheme = HTTPBearer(auto_error=False)

_TOKEN_TYPE_ACCESS = "access"
_TOKEN_TYPE_REFRESH = "refresh"


# ----------------------------------------------------------------------
# Password hashing
# ----------------------------------------------------------------------
def hash_password(plain_password: str) -> str:
    """Hashes a plaintext password with bcrypt. Never store plaintext."""
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verifies a plaintext password against a stored bcrypt hash."""
    return _pwd_context.verify(plain_password, password_hash)


# ----------------------------------------------------------------------
# JWT creation
# ----------------------------------------------------------------------
def create_access_token(user_id: str, business_id: str, role: str) -> str:
    """
    Issues a short-lived access token carrying user_id, business_id, and
    role — these three claims are what let every downstream route scope
    its queries to the caller's tenant and enforce RBAC without an extra
    DB round-trip on every request.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "business_id": business_id,
        "role": role,
        "type": _TOKEN_TYPE_ACCESS,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> tuple[str, datetime]:
    """
    Issues a long-lived refresh token. Deliberately carries only `sub`
    (user_id) and `type` — no business_id/role, since those are re-derived
    from the user record at refresh time rather than trusted from an
    old token, in case the user's role changed since it was issued.

    Returns (token, expires_at) — the caller (auth_routes.py) persists
    both via refresh_tokens_repo.store_refresh_token so logout can look
    up and revoke a specific token.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": user_id,
        "type": _TOKEN_TYPE_REFRESH,
        "iat": now,
        "exp": expire,
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expire


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    """
    Decodes and validates a JWT, checking both signature/expiry (handled
    by jose) and that the token's `type` claim matches what the caller
    expects — this is what prevents a refresh token from being used as
    an access token or vice versa.

    Raises JWTError (or ValueError for a type mismatch) on any failure;
    callers in this module catch and translate to AppError.
    """
    payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    if payload.get("type") != expected_type:
        raise ValueError(f"Expected token type '{expected_type}', got '{payload.get('type')}'.")
    return payload


# ----------------------------------------------------------------------
# FastAPI dependencies
# ----------------------------------------------------------------------
async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> UserModel:
    """
    Resolves the authenticated UserModel from the request's bearer token.

    Used as `Depends(get_current_user)` on every protected route. Raises
    a uniform 401 UNAUTHORIZED AppError for every failure mode (missing
    header, malformed token, expired token, wrong token type, user no
    longer exists, user deactivated) — deliberately not distinguishing
    between these in the response, since revealing *why* a token is
    invalid is not useful to a legitimate caller and is mildly useful to
    an attacker probing the auth layer.
    """
    if credentials is None:
        raise AppError(
            status_code=401,
            code="UNAUTHORIZED",
            message="Missing or invalid authorization header.",
        )

    try:
        payload = decode_token(credentials.credentials, expected_type=_TOKEN_TYPE_ACCESS)
    except (JWTError, ValueError) as exc:
        logger.info("Access token rejected: %s", exc)
        raise AppError(
            status_code=401,
            code="UNAUTHORIZED",
            message="Missing or invalid authorization header.",
        ) from exc

    user_id = payload.get("sub")
    if not user_id:
        raise AppError(status_code=401, code="UNAUTHORIZED", message="Invalid token payload.")

    # Imported here (rather than at module top) to avoid a circular import:
    # users_repo will, in turn, depend on models defined alongside this
    # module's imports in some configurations. Keeping this import local
    # keeps app/core/security.py safely low in the dependency graph.
    from app.db.repositories import users_repo

    user = await users_repo.get_by_id(db, user_id)
    if user is None:
        raise AppError(status_code=401, code="UNAUTHORIZED", message="User no longer exists.")

    if not user.is_active:
        raise AppError(status_code=403, code="ACCOUNT_DISABLED", message="This account has been deactivated.")

    return user


def require_roles(*allowed_roles: UserRole):
    """
    Dependency factory for role-gated routes. Usage:

        Depends(require_roles(UserRole.ADMIN, UserRole.ANALYST))

    Chains on top of get_current_user (auth is always checked first),
    then verifies the resolved user's role is one of `allowed_roles`,
    raising 403 FORBIDDEN otherwise. Returns the same UserModel
    get_current_user would, so routes can type their dependency
    identically regardless of whether they used get_current_user or
    require_roles directly.
    """

    async def _dependency(current_user: UserModel = Depends(get_current_user)) -> UserModel:
        if current_user.role not in allowed_roles:
            raise AppError(
                status_code=403,
                code="FORBIDDEN",
                message="You do not have permission to perform this action.",
            )
        return current_user

    return _dependency
