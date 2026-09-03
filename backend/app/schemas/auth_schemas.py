"""
app/schemas/auth_schemas.py

Request/response Pydantic models for Section A (Authentication) of the
approved API spec — Register, Login, Logout.

Distinct from app/models/user.py: that file is the MongoDB-facing
representation (includes password_hash, _id, is_active, etc.); this file
is the API-facing representation (accepts a plaintext password on
input, never exposes password_hash on output). Keep it that way — do
not import UserModel's sensitive fields into a response model here.
"""

import re

from pydantic import BaseModel, EmailStr, Field, field_validator

# Minimum password requirements, enforced on RegisterRequest only (not
# LoginRequest — a login should never fail for not meeting today's
# policy, only for not matching the stored hash).
_PASSWORD_MIN_LENGTH = 10
_PASSWORD_PATTERNS = {
    "uppercase": re.compile(r"[A-Z]"),
    "lowercase": re.compile(r"[a-z]"),
    "digit": re.compile(r"\d"),
    "symbol": re.compile(r"[^A-Za-z0-9]"),
}


def _validate_password_strength(password: str) -> str:
    if len(password) < _PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {_PASSWORD_MIN_LENGTH} characters long.")
    missing = [name for name, pattern in _PASSWORD_PATTERNS.items() if not pattern.search(password)]
    if missing:
        raise ValueError(
            "Password must include at least one uppercase letter, one lowercase "
            "letter, one digit, and one symbol. Missing: " + ", ".join(missing)
        )
    return password


# ----------------------------------------------------------------------
# A.1 Register
# ----------------------------------------------------------------------
class RegisterRequest(BaseModel):
    """Request body for POST /auth/register."""

    business_name: str = Field(..., min_length=2, max_length=120)
    admin_name: str = Field(..., min_length=2, max_length=80)
    email: EmailStr
    password: str
    razorpay_key_id: str | None = Field(default=None)
    razorpay_key_secret: str | None = Field(default=None)

    @field_validator("password")
    @classmethod
    def password_must_be_strong(cls, v: str) -> str:
        return _validate_password_strength(v)


# ----------------------------------------------------------------------
# A.2 Login
# ----------------------------------------------------------------------
class LoginRequest(BaseModel):
    """Request body for POST /auth/login. No strength validation here."""

    email: EmailStr
    password: str = Field(..., min_length=1)


# ----------------------------------------------------------------------
# A.3 Logout
# ----------------------------------------------------------------------
class LogoutRequest(BaseModel):
    """Request body for POST /auth/logout."""

    refresh_token: str = Field(..., min_length=1)


# ----------------------------------------------------------------------
# Shared response: Register (201) and Login (200)
# ----------------------------------------------------------------------
class TokenResponse(BaseModel):
    """
    Response body for both POST /auth/register and POST /auth/login —
    the approved API spec documents identical shapes for both.
    """

    business_id: str
    user_id: str
    email: EmailStr
    role: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
