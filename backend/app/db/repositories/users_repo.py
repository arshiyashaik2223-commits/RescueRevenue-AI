"""
app/db/repositories/users_repo.py

Data access layer for the `Users` collection. This is the only file
allowed to run MongoDB queries against `users` directly — services,
routes, and app/core/security.py all go through the functions here.

Depends on (generated in an upcoming file):
  - app.db.repositories.businesses_repo : create_business
    (used only by create_business_and_admin, for the registration flow)
"""

import logging
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.user import UserCreate, UserModel

logger = logging.getLogger(__name__)

_COLLECTION = "users"


def _safe_object_id(value: str | ObjectId) -> ObjectId | None:
    """
    Coerces a value into an ObjectId, returning None (rather than
    raising) on an invalid string — callers treat None the same as
    "not found", which is the correct behavior for a lookup by a
    caller-supplied ID that might simply be malformed.
    """
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


async def get_by_id(db: AsyncIOMotorDatabase, user_id: str | ObjectId) -> UserModel | None:
    """
    Fetches a single user by ID. Returns None for both "no such user"
    and "user_id was not a valid ObjectId" — callers (notably
    get_current_user in app/core/security.py) treat both identically.
    """
    oid = _safe_object_id(user_id)
    if oid is None:
        return None

    document = await db[_COLLECTION].find_one({"_id": oid})
    if document is None:
        return None
    return UserModel.from_mongo(document)


async def get_by_email(db: AsyncIOMotorDatabase, email: str) -> UserModel | None:
    """
    Fetches a single user by email. Email is the unique login
    identifier (see the unique index on users.email in
    app/db/database.py), so this is safe to treat as at-most-one-result.
    Lookup is case-insensitive to avoid duplicate-looking accounts from
    inconsistent casing at signup vs. login.
    """
    document = await db[_COLLECTION].find_one({"email": {"$regex": f"^{_escape_regex(email)}$", "$options": "i"}})
    if document is None:
        return None
    return UserModel.from_mongo(document)


async def create_user(db: AsyncIOMotorDatabase, user: UserCreate) -> UserModel:
    """
    Inserts a new user document for an already-existing business.
    For the combined "create business + first admin" registration flow,
    use create_business_and_admin() instead.
    """
    now = datetime.now(timezone.utc)
    document = {
        "business_id": user.business_id,
        "name": user.name,
        "email": user.email,
        "password_hash": user.password_hash,
        "role": user.role.value,
        "is_active": user.is_active,
        "last_login_at": None,
        "created_at": now,
        "updated_at": now,
    }
    result = await db[_COLLECTION].insert_one(document)
    document["_id"] = result.inserted_id
    return UserModel.from_mongo(document)


async def create_business_and_admin(
    db: AsyncIOMotorDatabase,
    business_name: str,
    razorpay_key_id: str | None,
    razorpay_key_secret: str | None,
    user: UserCreate,
) -> tuple[ObjectId, UserModel]:
    """
    Registration orchestration: creates the business (tenant) record
    first, then creates the admin user against the resulting real
    business_id — overwriting whatever placeholder business_id the
    caller's UserCreate was constructed with (see
    app/api/v1/auth_routes.py's business_id_placeholder() for why that
    placeholder exists).

    Not wrapped in a MongoDB multi-document transaction in this v1
    implementation (that requires a replica-set-backed Atlas cluster,
    which is assumed but not guaranteed for local/hackathon dev). If
    business creation succeeds but user creation fails, the business
    record is orphaned rather than corrupted — an acceptable v1
    trade-off flagged here for visibility; revisit with a transaction
    (Motor supports client.start_session()) before scaling to
    production multi-tenant traffic.
    """
    from app.db.repositories import businesses_repo  # local import: avoids a
    # circular dependency, since businesses_repo may in turn want to import
    # shared helpers that live alongside user-repo-adjacent modules.

    business_id = await businesses_repo.create_business(
        db,
        name=business_name,
        razorpay_key_id=razorpay_key_id,
        razorpay_key_secret=razorpay_key_secret,
    )

    user_with_real_business_id = user.model_copy(update={"business_id": business_id})
    created_user = await create_user(db, user_with_real_business_id)

    logger.info("Registration complete: business_id=%s admin_user_id=%s", business_id, created_user.id)

    return business_id, created_user


async def update_last_login(db: AsyncIOMotorDatabase, user_id: str | ObjectId) -> None:
    """Stamps last_login_at on successful authentication."""
    oid = _safe_object_id(user_id)
    if oid is None:
        return
    now = datetime.now(timezone.utc)
    await db[_COLLECTION].update_one(
        {"_id": oid},
        {"$set": {"last_login_at": now, "updated_at": now}},
    )


def _escape_regex(value: str) -> str:
    """Escapes regex special characters in a case-insensitive email lookup."""
    import re

    return re.escape(value)
