"""
app/db/repositories/recovery_actions_repo.py
Data access layer for the RecoveryActions collection.
"""
import logging
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.recovery_action import ActionStatus, RecoveryActionCreate, RecoveryActionModel

logger = logging.getLogger(__name__)

_COLLECTION = "recovery_actions"


def _safe_object_id(value):
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


async def create_recovery_action(db: AsyncIOMotorDatabase, payload: RecoveryActionCreate) -> RecoveryActionModel:
    document = payload.model_dump()
    document["status"] = ActionStatus.SCHEDULED.value
    document["executed_at"] = None
    document["message_content"] = None
    document["outcome"] = None
    document["created_at"] = datetime.now(timezone.utc)
    result = await db[_COLLECTION].insert_one(document)
    document["_id"] = result.inserted_id
    return RecoveryActionModel.from_mongo(document)


async def count_for_failed_payment(db: AsyncIOMotorDatabase, failed_payment_id) -> int:
    oid = _safe_object_id(failed_payment_id)
    if oid is None:
        return 0
    return await db[_COLLECTION].count_documents({"failed_payment_id": oid})


async def get_by_id_unscoped(db: AsyncIOMotorDatabase, action_id: str) -> RecoveryActionModel | None:
    """Used by Celery workers acting on a known-valid action ID (no tenant scoping needed)."""
    oid = _safe_object_id(action_id)
    if oid is None:
        return None
    document = await db[_COLLECTION].find_one({"_id": oid})
    return RecoveryActionModel.from_mongo(document) if document else None


async def list_by_failed_payment(db: AsyncIOMotorDatabase, failed_payment_id) -> list[RecoveryActionModel]:
    oid = _safe_object_id(failed_payment_id)
    if oid is None:
        return []
    cursor = db[_COLLECTION].find({"failed_payment_id": oid}).sort("sequence_step", 1)
    return [RecoveryActionModel.from_mongo(doc) async for doc in cursor]


async def update_execution(
    db: AsyncIOMotorDatabase,
    action_id,
    status: ActionStatus,
    message_content: dict | None = None,
    outcome: str | None = None,
) -> bool:
    oid = _safe_object_id(action_id)
    if oid is None:
        return False
    update: dict = {"status": status.value, "executed_at": datetime.now(timezone.utc)}
    if message_content is not None:
        update["message_content"] = message_content
    if outcome is not None:
        update["outcome"] = outcome
    result = await db[_COLLECTION].update_one({"_id": oid}, {"$set": update})
    return result.matched_count > 0
