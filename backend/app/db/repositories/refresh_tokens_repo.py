"""
app/db/repositories/refresh_tokens_repo.py

Data access layer for the `refresh_tokens` collection — persisted
records of issued refresh tokens, which is what makes logout actually
revoke a session rather than just being a no-op against a stateless JWT.

Not one of the six collections detailed in the approved database schema
doc (same situation as businesses_repo.py) — introduced here because
app.api.v1.auth_routes.py's Logout endpoint requires some persisted
concept of "this refresh token has been revoked" to function at all.

SECURITY NOTE: tokens are stored as SHA-256 hashes, never in plaintext.
A raw refresh token in this collection would be a usable credential —
hashing it means a database read alone can't be used to impersonate a
session. This mirrors why app.models.user.UserModel stores
password_hash rather than a plaintext password.

Depends on: nothing beyond Motor/the database handle (leaf repository,
same tier as users_repo.py and businesses_repo.py).
"""

import hashlib
import logging
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

_COLLECTION = "refresh_tokens"


def _hash_token(token: str) -> str:
    """
    SHA-256 hash of the raw token string. Deliberately unsalted — unlike
    passwords, refresh tokens are already high-entropy random-looking
    JWTs (not user-chosen low-entropy secrets), so a rainbow-table
    attack isn't a meaningful risk, and a salted hash would require
    storing the salt anyway. A plain SHA-256 digest is standard practice
    for token-at-rest hashing (e.g. this is the same approach OAuth
    providers commonly use for stored access/refresh tokens).
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _safe_object_id(value: str | ObjectId) -> ObjectId | None:
    """Same defensive coercion pattern used in users_repo.py / businesses_repo.py."""
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


async def store_refresh_token(
    db: AsyncIOMotorDatabase,
    user_id: str | ObjectId,
    token: str,
    expires_at: datetime,
) -> None:
    """
    Persists a newly issued refresh token (hashed) so it can later be
    looked up and revoked. Called from auth_routes.py immediately after
    create_refresh_token() on both register and login.
    """
    oid = _safe_object_id(user_id)
    if oid is None:
        logger.warning("store_refresh_token called with invalid user_id=%r", user_id)
        return

    document = {
        "user_id": oid,
        "token_hash": _hash_token(token),
        "expires_at": expires_at,
        "revoked_at": None,
        "created_at": datetime.now(timezone.utc),
    }
    await db[_COLLECTION].insert_one(document)


async def revoke_refresh_token(db: AsyncIOMotorDatabase, user_id: str | ObjectId, token: str) -> bool:
    """
    Marks a specific refresh token as revoked, scoped to the given
    user_id (so a caller can only ever revoke their own sessions — this
    is enforced by auth_routes.logout() passing current_user.id, not by
    anything in this function alone, but the scoping here is a second
    layer of the same guarantee).

    Returns True if a matching, not-already-revoked, not-expired
    document was found and updated; False otherwise (used by
    auth_routes.logout() to raise 404 SESSION_NOT_FOUND).
    """
    oid = _safe_object_id(user_id)
    if oid is None:
        return False

    now = datetime.now(timezone.utc)
    result = await db[_COLLECTION].update_one(
        {
            "user_id": oid,
            "token_hash": _hash_token(token),
            "revoked_at": None,
            "expires_at": {"$gt": now},
        },
        {"$set": {"revoked_at": now}},
    )
    return result.matched_count > 0


async def is_refresh_token_valid(db: AsyncIOMotorDatabase, token: str) -> bool:
    """
    True if the given refresh token has a stored record that is neither
    revoked nor expired. Intended for a future POST /auth/refresh
    endpoint (not yet in the approved API spec's three Authentication
    endpoints, but a natural addition once access tokens start expiring
    in real usage) to check before minting a new access token.
    """
    now = datetime.now(timezone.utc)
    document = await db[_COLLECTION].find_one(
        {
            "token_hash": _hash_token(token),
            "revoked_at": None,
            "expires_at": {"$gt": now},
        }
    )
    return document is not None


async def revoke_all_for_user(db: AsyncIOMotorDatabase, user_id: str | ObjectId) -> int:
    """
    Revokes every active refresh token for a user — useful for a future
    "log out of all devices" action or as a security response when an
    account is deactivated. Returns the number of tokens revoked.
    """
    oid = _safe_object_id(user_id)
    if oid is None:
        return 0

    now = datetime.now(timezone.utc)
    result = await db[_COLLECTION].update_many(
        {"user_id": oid, "revoked_at": None, "expires_at": {"$gt": now}},
        {"$set": {"revoked_at": now}},
    )
    return result.modified_count
