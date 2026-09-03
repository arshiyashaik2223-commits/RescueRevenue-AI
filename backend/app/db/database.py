"""
app/db/database.py

MongoDB connection lifecycle management (async, via Motor).

This is the single place in the codebase that holds a raw MongoDB client.
Every file under `app/db/repositories/` depends on `get_database()` here
to obtain a database handle — no other layer (services, api, workers)
should import Motor/PyMongo directly.

Responsibilities:
  - Create and cache a single AsyncIOMotorClient for the process lifetime.
  - Expose `connect_to_mongo()` / `close_mongo_connection()`, called from
    FastAPI's startup/shutdown events in `app/main.py`.
  - Expose `get_database()`, used both as a plain accessor and as a
    FastAPI dependency for route handlers that need direct DB access.
  - Create indexes (per the approved database schema doc) once at
    startup, idempotently.
"""

import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.config import settings

logger = logging.getLogger(__name__)


class MongoDBConnection:
    """
    Thin wrapper holding the Motor client + database handle.

    Instantiated once as a module-level singleton (`mongodb`, below) so
    that `connect_to_mongo()` / `get_database()` / `close_mongo_connection()`
    all operate on the same underlying connection pool.
    """

    client: AsyncIOMotorClient | None = None
    db: AsyncIOMotorDatabase | None = None


mongodb = MongoDBConnection()


async def connect_to_mongo() -> None:
    """
    Opens the MongoDB connection pool and verifies connectivity.

    Called once from the FastAPI startup event in `app/main.py`. Raises
    on failure so the app fails fast at boot rather than serving traffic
    against a broken database connection.
    """
    logger.info("Connecting to MongoDB at %s ...", _redact_uri(settings.MONGO_URI))

    mongodb.client = AsyncIOMotorClient(settings.MONGO_URI)
    mongodb.db = mongodb.client[settings.MONGO_DB_NAME]

    # Fail fast if the connection is unreachable/misconfigured.
    await mongodb.client.admin.command("ping")
    logger.info("MongoDB connection established (db=%s).", settings.MONGO_DB_NAME)

    await _ensure_indexes(mongodb.db)


async def close_mongo_connection() -> None:
    """
    Closes the MongoDB connection pool.

    Called once from the FastAPI shutdown event in `app/main.py`.
    """
    if mongodb.client is not None:
        mongodb.client.close()
        logger.info("MongoDB connection closed.")


def get_database() -> AsyncIOMotorDatabase:
    """
    Returns the active database handle.

    Used both as a direct call (e.g. inside `connect_to_mongo`) and as a
    FastAPI dependency:

        from fastapi import Depends
        from app.db.database import get_database

        @router.get("/example")
        async def example(db = Depends(get_database)):
            ...

    Raises RuntimeError if called before `connect_to_mongo()` has run,
    which should only happen if a route bypasses the app lifecycle
    (e.g. in a misconfigured test) — surfacing loudly is preferable to
    a confusing AttributeError deep in a repository.
    """
    if mongodb.db is None:
        raise RuntimeError(
            "Database accessed before connection was established. "
            "Ensure connect_to_mongo() has run (see app/main.py startup event)."
        )
    return mongodb.db


async def _ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """
    Creates all indexes recommended in the approved database schema
    document, idempotently (create_indexes is a no-op for indexes that
    already exist with the same spec).

    Kept in this file (rather than scattered per-repository) so the full
    index strategy is visible and auditable in one place, matching the
    schema doc's "Recommended Indexes" sections.
    """
    logger.info("Ensuring MongoDB indexes...")

    # --- Users ---
    await db["users"].create_indexes(
        [
            IndexModel([("email", ASCENDING)], unique=True, name="uniq_email"),
            IndexModel([("business_id", ASCENDING)], name="business_id"),
            IndexModel(
                [("business_id", ASCENDING), ("role", ASCENDING)],
                name="business_id_role",
            ),
        ]
    )

    # --- Transactions ---
    await db["transactions"].create_indexes(
        [
            IndexModel(
                [("business_id", ASCENDING), ("occurred_at", DESCENDING)],
                name="business_id_occurred_at",
            ),
            IndexModel(
                [("razorpay_payment_id", ASCENDING)],
                unique=True,
                sparse=True,
                name="uniq_razorpay_payment_id",
            ),
            IndexModel([("razorpay_order_id", ASCENDING)], name="razorpay_order_id"),
            IndexModel(
                [("business_id", ASCENDING), ("status", ASCENDING), ("type", ASCENDING)],
                name="business_id_status_type",
            ),
            IndexModel([("customer.customer_id", ASCENDING)], name="customer_id"),
        ]
    )

    # --- FailedPayments ---
    await db["failed_payments"].create_indexes(
        [
            IndexModel(
                [("business_id", ASCENDING), ("status", ASCENDING)],
                name="business_id_status",
            ),
            IndexModel(
                [("transaction_id", ASCENDING)],
                unique=True,
                name="uniq_transaction_id",
            ),
            IndexModel(
                [("business_id", ASCENDING), ("detected_at", DESCENDING)],
                name="business_id_detected_at",
            ),
            IndexModel([("customer.customer_id", ASCENDING)], name="customer_id"),
            IndexModel(
                [("business_id", ASCENDING), ("failure_reason_category", ASCENDING)],
                name="business_id_failure_reason",
            ),
        ]
    )

    # --- RecoveryPredictions ---
    await db["recovery_predictions"].create_indexes(
        [
            IndexModel(
                [("failed_payment_id", ASCENDING)],
                unique=True,
                partialFilterExpression={"is_current": True},
                name="uniq_current_prediction_per_case",
            ),
            IndexModel(
                [("failed_payment_id", ASCENDING), ("is_current", ASCENDING)],
                name="failed_payment_id_is_current",
            ),
            IndexModel(
                [("business_id", ASCENDING), ("risk_tier", ASCENDING)],
                name="business_id_risk_tier",
            ),
            IndexModel([("predicted_at", DESCENDING)], name="predicted_at"),
            IndexModel([("model_version", ASCENDING)], name="model_version"),
        ]
    )

    # --- RecoveryActions ---
    await db["recovery_actions"].create_indexes(
        [
            IndexModel(
                [("failed_payment_id", ASCENDING), ("sequence_step", ASCENDING)],
                name="failed_payment_id_sequence_step",
            ),
            IndexModel(
                [
                    ("business_id", ASCENDING),
                    ("status", ASCENDING),
                    ("scheduled_at", ASCENDING),
                ],
                name="business_id_status_scheduled_at",
            ),
            IndexModel(
                [("status", ASCENDING), ("scheduled_at", ASCENDING)],
                name="status_scheduled_at",
            ),
            IndexModel(
                [("triggered_by_user_id", ASCENDING)],
                sparse=True,
                name="triggered_by_user_id",
            ),
        ]
    )

    # --- AIInsights ---
    await db["ai_insights"].create_indexes(
        [
            IndexModel(
                [("business_id", ASCENDING), ("created_at", DESCENDING)],
                name="business_id_created_at",
            ),
            IndexModel(
                [("question_hash", ASCENDING), ("business_id", ASCENDING)],
                name="question_hash_business_id",
            ),
            IndexModel(
                [("ttl_at", ASCENDING)],
                expireAfterSeconds=0,
                name="ttl_at_expiry",
            ),
            IndexModel([("user_id", ASCENDING)], name="user_id"),
        ]
    )

    logger.info("MongoDB indexes ensured.")


def _redact_uri(uri: str) -> str:
    """Hides credentials in the connection string when logging it."""
    if "@" in uri and "://" in uri:
        scheme, rest = uri.split("://", 1)
        _, _, host_part = rest.partition("@")
        return f"{scheme}://***:***@{host_part}"
    return uri
