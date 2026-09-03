"""
app/db/repositories/businesses_repo.py

Data access layer for the `businesses` collection — the tenant record
every other collection's business_id foreign key references. Not one of
the six collections detailed in the approved database schema doc, but
assumed there (and in the architecture doc, Section 6.2) to exist.

This is a leaf repository: it has no dependencies on other repositories.
app.db.repositories.users_repo depends on this file (create_business_and_admin
calls create_business here); app.api.v1.webhook_routes depends on this
file (get_webhook_secret).

NOTE on secrets: for v1/hackathon scope, Razorpay credentials and the
webhook secret are stored directly on the business document. The
architecture doc's production design routes these through a secret
manager instead (see .env.example's note on per-business keys) — that
hardening is flagged here as a follow-up, not implemented in this pass.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

_COLLECTION = "businesses"


def _safe_object_id(value: str | ObjectId) -> ObjectId | None:
    """Same defensive coercion pattern used in users_repo.py."""
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


async def create_business(
    db: AsyncIOMotorDatabase,
    name: str,
    razorpay_key_id: str | None = None,
    razorpay_key_secret: str | None = None,
) -> ObjectId:
    """
    Creates a new business (tenant) record. Called exclusively from
    users_repo.create_business_and_admin() during registration.

    webhook_secret starts unset (None) — a business configures it
    separately once they set up their Razorpay webhook URL and get a
    secret from the Razorpay dashboard (via the Settings API's
    PUT /settings/razorpay-keys, per the architecture doc — not yet
    generated). brand_voice_config and notification_channels are seeded
    with sensible defaults so the message-generation and notification
    services (upcoming) always have something to read.
    """
    now = datetime.now(timezone.utc)
    document = {
        "name": name,
        "razorpay_key_id": razorpay_key_id,
        "razorpay_key_secret": razorpay_key_secret,
        "webhook_secret": None,
        "brand_voice_config": {
            "tone": "helpful and professional",
            "signature": name,
        },
        "notification_channels": {
            "email": True,
            "sms": False,
            "whatsapp": False,
        },
        "plan": "trial",
        "created_at": now,
        "updated_at": now,
    }
    result = await db[_COLLECTION].insert_one(document)
    logger.info("Business created: business_id=%s name=%s", result.inserted_id, name)
    return result.inserted_id


async def get_by_id(db: AsyncIOMotorDatabase, business_id: str | ObjectId) -> dict[str, Any] | None:
    """
    Fetches the raw business document by ID. Returned as a plain dict
    rather than a Pydantic model — `businesses` wasn't one of the six
    modeled collections in the approved schema doc, so callers that need
    typed access (e.g. a future Settings service) are expected to shape
    the fields they need themselves rather than this repo committing to
    a schema that hasn't been formally approved yet.
    """
    oid = _safe_object_id(business_id)
    if oid is None:
        return None
    return await db[_COLLECTION].find_one({"_id": oid})


async def get_webhook_secret(db: AsyncIOMotorDatabase, business_id: str | ObjectId) -> str | None:
    """
    Returns the business's configured Razorpay webhook secret, or None
    if the business doesn't exist OR exists but hasn't configured one
    yet (see the explanation given alongside this file for why both
    cases collapse to None here).
    """
    document = await get_by_id(db, business_id)
    if document is None:
        return None
    return document.get("webhook_secret")


async def set_webhook_secret(db: AsyncIOMotorDatabase, business_id: str | ObjectId, secret: str) -> bool:
    """
    Sets/updates the business's Razorpay webhook secret. Used by the
    upcoming Settings API (PUT /settings/razorpay-keys) once a business
    configures their webhook in the Razorpay dashboard and pastes the
    resulting secret in. Returns True if a document was updated.
    """
    oid = _safe_object_id(business_id)
    if oid is None:
        return False
    result = await db[_COLLECTION].update_one(
        {"_id": oid},
        {"$set": {"webhook_secret": secret, "updated_at": datetime.now(timezone.utc)}},
    )
    return result.matched_count > 0


async def update_razorpay_keys(
    db: AsyncIOMotorDatabase,
    business_id: str | ObjectId,
    razorpay_key_id: str,
    razorpay_key_secret: str,
) -> bool:
    """
    Updates a business's Razorpay API credentials. Used by the upcoming
    Settings API. Returns True if a document was updated.
    """
    oid = _safe_object_id(business_id)
    if oid is None:
        return False
    result = await db[_COLLECTION].update_one(
        {"_id": oid},
        {
            "$set": {
                "razorpay_key_id": razorpay_key_id,
                "razorpay_key_secret": razorpay_key_secret,
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )
    return result.matched_count > 0
