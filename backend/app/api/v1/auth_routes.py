"""
app/api/v1/auth_routes.py

Authentication endpoints: Register, Login, Logout.
Implements Section A of RevenueRescue-AI-API-Specification.md exactly —
URLs, request/response shapes, validation rules, and error codes below
all mirror that document.

Depends on (generated in upcoming files):
  - app.schemas.auth_schemas   : RegisterRequest, LoginRequest, LogoutRequest,
                                  TokenResponse, RegisterResponse
  - app.core.security          : hash_password, verify_password,
                                  create_access_token, create_refresh_token,
                                  decode_token, get_current_user
  - app.db.repositories.users_repo : get_by_email, create_user, update_last_login
  - app.db.repositories.refresh_tokens_repo : store_refresh_token,
                                  revoke_refresh_token, is_refresh_token_valid
  - app.services.razorpay_client   : verify_credentials (used only if
                                  razorpay keys are supplied at registration)
"""

import logging

from fastapi import APIRouter, Depends, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.exceptions import AppError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.db.database import get_database
from app.db.repositories import refresh_tokens_repo, users_repo
from app.models.user import UserCreate, UserModel, UserRole
from app.schemas.auth_schemas import (
    LoginRequest,
    LogoutRequest,
    RegisterRequest,
    TokenResponse,
)
from app.services import razorpay_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ----------------------------------------------------------------------
# A.1 Register
# ----------------------------------------------------------------------
@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new business + first admin user",
)
async def register(
    payload: RegisterRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> TokenResponse:
    """
    Creates a new business (tenant) plus its first admin user.

    Validation (enforced partly here, partly via Pydantic on RegisterRequest):
      - email must be unique across Users (checked here -> 409 EMAIL_ALREADY_EXISTS)
      - password strength enforced by the schema's field validator
      - razorpay_key_id / razorpay_key_secret: optional; if provided, both
        required together and verified against Razorpay before saving
        (-> 502 RAZORPAY_KEY_INVALID on failure)
    """
    existing = await users_repo.get_by_email(db, payload.email)
    if existing is not None:
        raise AppError(
            status_code=status.HTTP_409_CONFLICT,
            code="EMAIL_ALREADY_EXISTS",
            message="An account with this email already exists.",
        )

    if payload.razorpay_key_id or payload.razorpay_key_secret:
        if not (payload.razorpay_key_id and payload.razorpay_key_secret):
            raise AppError(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="RAZORPAY_KEYS_INCOMPLETE",
                message="Both razorpay_key_id and razorpay_key_secret are required together.",
            )
        is_valid = await razorpay_client.verify_credentials(
            payload.razorpay_key_id, payload.razorpay_key_secret
        )
        if not is_valid:
            raise AppError(
                status_code=status.HTTP_502_BAD_GATEWAY,
                code="RAZORPAY_KEY_INVALID",
                message="Could not verify Razorpay credentials.",
            )

    # Creates the business record and the first admin user together.
    # business creation itself is delegated to users_repo.create_business_and_admin
    # so this stays a single atomic-ish operation (see repo for transaction handling).
    business_id, user = await users_repo.create_business_and_admin(
        db,
        business_name=payload.business_name,
        razorpay_key_id=payload.razorpay_key_id,
        razorpay_key_secret=payload.razorpay_key_secret,
        user=UserCreate(
            business_id=business_id_placeholder(),  # replaced inside repo once business_id is known
            name=payload.admin_name,
            email=payload.email,
            password_hash=hash_password(payload.password),
            role=UserRole.ADMIN,
        ),
    )

    access_token = create_access_token(user_id=str(user.id), business_id=str(business_id), role=user.role.value)
    refresh_token, expires_at = create_refresh_token(user_id=str(user.id))
    await refresh_tokens_repo.store_refresh_token(db, user_id=user.id, token=refresh_token, expires_at=expires_at)

    logger.info("New business registered: business_id=%s user_id=%s", business_id, user.id)

    return TokenResponse(
        business_id=str(business_id),
        user_id=str(user.id),
        email=user.email,
        role=user.role.value,
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=3600,
    )


# ----------------------------------------------------------------------
# A.2 Login
# ----------------------------------------------------------------------
@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate and receive access + refresh tokens",
)
async def login(
    payload: LoginRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> TokenResponse:
    """
    Authenticates a user by email + password.

    Error responses (per API spec):
      - 401 INVALID_CREDENTIALS : email not found OR password mismatch
        (deliberately identical message for both, to avoid revealing
        which part was wrong)
      - 403 ACCOUNT_DISABLED    : user.is_active is False
      - 429 RATE_LIMITED        : too many recent failed attempts
        (enforced by rate-limit middleware/dependency, not shown here)
    """
    user: UserModel | None = await users_repo.get_by_email(db, payload.email)

    if user is None or not verify_password(payload.password, user.password_hash):
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_CREDENTIALS",
            message="Email or password is incorrect.",
        )

    if not user.is_active:
        raise AppError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="ACCOUNT_DISABLED",
            message="This account has been deactivated.",
        )

    access_token = create_access_token(
        user_id=str(user.id), business_id=str(user.business_id), role=user.role.value
    )
    refresh_token, expires_at = create_refresh_token(user_id=str(user.id))
    await refresh_tokens_repo.store_refresh_token(db, user_id=user.id, token=refresh_token, expires_at=expires_at)
    await users_repo.update_last_login(db, user_id=user.id)

    return TokenResponse(
        business_id=str(user.business_id),
        user_id=str(user.id),
        email=user.email,
        role=user.role.value,
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=3600,
    )


# ----------------------------------------------------------------------
# A.3 Logout
# ----------------------------------------------------------------------
@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Revoke the current refresh token",
)
async def logout(
    payload: LogoutRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: UserModel = Depends(get_current_user),
) -> dict:
    """
    Invalidates the supplied refresh token for the authenticated user.
    Access tokens remain short-lived and simply expire; this only revokes
    the ability to mint new access tokens from this session.

    Error responses (per API spec):
      - 401 UNAUTHORIZED    : missing/invalid access token on the request itself
                               (enforced by the get_current_user dependency)
      - 422 VALIDATION_ERROR: refresh_token missing from body (enforced by schema)
      - 404 SESSION_NOT_FOUND: refresh token already revoked/expired, or does
                               not belong to this user
    """
    revoked = await refresh_tokens_repo.revoke_refresh_token(
        db, user_id=current_user.id, token=payload.refresh_token
    )
    if not revoked:
        raise AppError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="SESSION_NOT_FOUND",
            message="This session is already invalid.",
        )

    return {"message": "Logged out successfully."}


def business_id_placeholder():
    """
    Internal helper: UserCreate requires a business_id at construction
    time, but the business document doesn't exist yet at the point this
    module builds the UserCreate payload. users_repo.create_business_and_admin
    creates the business first and overwrites this placeholder with the
    real business_id before persisting the user — see that repo function
    (upcoming file) for the actual sequencing/transaction handling.
    """
    from bson import ObjectId

    return ObjectId()
