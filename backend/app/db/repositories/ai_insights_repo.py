"""
app/db/repositories/ai_insights_repo.py
Data access layer for the AIInsights collection.
"""
import logging
from datetime import date, datetime, time, timezone

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.ai_insight import AIInsightCreate, AIInsightModel

logger = logging.getLogger(__name__)

_COLLECTION = "ai_insights"


def _safe_object_id(value):
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


async def create_insight(db: AsyncIOMotorDatabase, payload: AIInsightCreate) -> AIInsightModel:
    document = payload.model_dump()
    document["created_at"] = datetime.now(timezone.utc)
    document["feedback"] = None
    result = await db[_COLLECTION].insert_one(document)
    document["_id"] = result.inserted_id
    return AIInsightModel.from_mongo(document)


async def get_cached_answer(db: AsyncIOMotorDatabase, business_id, question_hash: str) -> AIInsightModel | None:
    biz_oid = _safe_object_id(business_id)
    if biz_oid is None:
        return None
    document = await db[_COLLECTION].find_one(
        {"business_id": biz_oid, "question_hash": question_hash},
        sort=[("created_at", -1)],
    )
    return AIInsightModel.from_mongo(document) if document else None


async def list_insights(
    db: AsyncIOMotorDatabase,
    business_id,
    user_id: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[AIInsightModel], int]:
    biz_oid = _safe_object_id(business_id)
    if biz_oid is None:
        return [], 0

    query: dict = {"business_id": biz_oid}
    if user_id:
        user_oid = _safe_object_id(user_id)
        if user_oid:
            query["user_id"] = user_oid
    date_range: dict = {}
    if from_date:
        date_range["$gte"] = datetime.combine(from_date, time.min, tzinfo=timezone.utc)
    if to_date:
        date_range["$lte"] = datetime.combine(to_date, time.max, tzinfo=timezone.utc)
    if date_range:
        query["created_at"] = date_range

    total_items = await db[_COLLECTION].count_documents(query)
    cursor = (
        db[_COLLECTION]
        .find(query)
        .sort("created_at", -1)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [AIInsightModel.from_mongo(doc) async for doc in cursor]
    return items, total_items
