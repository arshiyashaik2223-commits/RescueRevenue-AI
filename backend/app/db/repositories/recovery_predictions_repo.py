"""
app/db/repositories/recovery_predictions_repo.py
Data access layer for the RecoveryPredictions collection.
"""
import logging
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.recovery_prediction import RecoveryPredictionCreate, RecoveryPredictionModel

logger = logging.getLogger(__name__)

_COLLECTION = "recovery_predictions"


def _safe_object_id(value):
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


async def get_current(db: AsyncIOMotorDatabase, failed_payment_id) -> RecoveryPredictionModel | None:
    oid = _safe_object_id(failed_payment_id)
    if oid is None:
        return None
    document = await db[_COLLECTION].find_one({"failed_payment_id": oid, "is_current": True})
    return RecoveryPredictionModel.from_mongo(document) if document else None


async def create_and_mark_current(
    db: AsyncIOMotorDatabase, payload: RecoveryPredictionCreate
) -> RecoveryPredictionModel:
    """
    Flips any existing current prediction for this failed_payment_id to
    is_current=False, then inserts the new one as current. Not wrapped
    in a transaction for the same replica-set-availability reason noted
    in users_repo.create_business_and_admin — acceptable for v1 given
    the brief window between the two writes.
    """
    await db[_COLLECTION].update_many(
        {"failed_payment_id": payload.failed_payment_id, "is_current": True},
        {"$set": {"is_current": False}},
    )

    document = payload.model_dump()
    document["is_current"] = True
    document["predicted_at"] = datetime.now(timezone.utc)
    result = await db[_COLLECTION].insert_one(document)
    document["_id"] = result.inserted_id
    return RecoveryPredictionModel.from_mongo(document)


async def get_history(db: AsyncIOMotorDatabase, failed_payment_id) -> list[RecoveryPredictionModel]:
    oid = _safe_object_id(failed_payment_id)
    if oid is None:
        return []
    cursor = db[_COLLECTION].find({"failed_payment_id": oid, "is_current": False}).sort("predicted_at", -1)
    return [RecoveryPredictionModel.from_mongo(doc) async for doc in cursor]
