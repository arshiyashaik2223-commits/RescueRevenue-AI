"""
app/db/repositories/failed_payments_repo.py
Data access layer for the FailedPayments collection.
"""
import logging
from datetime import date, datetime, time, timezone

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.failed_payment import FailedPaymentCreate, FailedPaymentModel, FailedPaymentStatus

logger = logging.getLogger(__name__)

_COLLECTION = "failed_payments"
_PREDICTIONS_COLLECTION = "recovery_predictions"


def _safe_object_id(value):
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


def _date_to_range(from_date, to_date) -> dict:
    range_filter: dict = {}
    if from_date:
        range_filter["$gte"] = datetime.combine(from_date, time.min, tzinfo=timezone.utc)
    if to_date:
        range_filter["$lte"] = datetime.combine(to_date, time.max, tzinfo=timezone.utc)
    return range_filter


async def create_failed_payment(db: AsyncIOMotorDatabase, payload: FailedPaymentCreate) -> FailedPaymentModel:
    now = datetime.now(timezone.utc)
    document = payload.model_dump()
    document.update(
        {
            "retry_attempts_count": 0,
            "status": FailedPaymentStatus.OPEN.value,
            "recovered_amount": None,
            "recovered_at": None,
            "detected_at": now,
            "updated_at": now,
        }
    )
    result = await db[_COLLECTION].insert_one(document)
    document["_id"] = result.inserted_id
    return FailedPaymentModel.from_mongo(document)


async def get_by_id(db: AsyncIOMotorDatabase, business_id, failed_payment_id: str) -> FailedPaymentModel | None:
    oid = _safe_object_id(failed_payment_id)
    biz_oid = _safe_object_id(business_id)
    if oid is None or biz_oid is None:
        return None
    document = await db[_COLLECTION].find_one({"_id": oid, "business_id": biz_oid})
    return FailedPaymentModel.from_mongo(document) if document else None


async def get_by_id_unscoped(db: AsyncIOMotorDatabase, failed_payment_id: str) -> FailedPaymentModel | None:
    """
    Fetches by ID without a business_id filter — used by Celery workers
    (tasks_scoring.py, tasks_notifications.py) acting on a document ID
    already known to be valid, rather than a caller-supplied ID needing
    tenant-isolation checking.
    """
    oid = _safe_object_id(failed_payment_id)
    if oid is None:
        return None
    document = await db[_COLLECTION].find_one({"_id": oid})
    return FailedPaymentModel.from_mongo(document) if document else None


async def get_by_transaction_id(
    db: AsyncIOMotorDatabase, business_id, transaction_id: str
) -> FailedPaymentModel | None:
    biz_oid = _safe_object_id(business_id)
    txn_oid = _safe_object_id(transaction_id)
    if biz_oid is None or txn_oid is None:
        return None
    document = await db[_COLLECTION].find_one({"business_id": biz_oid, "transaction_id": txn_oid})
    return FailedPaymentModel.from_mongo(document) if document else None


async def get_open_by_customer_and_amount(
    db: AsyncIOMotorDatabase, business_id, customer_id: str, amount: int
) -> FailedPaymentModel | None:
    """
    Best-effort reconciliation lookup: finds an OPEN failed payment for
    the same customer/amount, used by event_ingestion_service to mark a
    case recovered when a later payment.captured event arrives for the
    same customer. Razorpay does not give a strict FK between a failed
    attempt and its eventual successful retry, so this heuristic match
    is the pragmatic v1 approach — flagged as a known limitation vs. a
    guaranteed match.
    """
    biz_oid = _safe_object_id(business_id)
    if biz_oid is None:
        return None
    document = await db[_COLLECTION].find_one(
        {
            "business_id": biz_oid,
            "customer.customer_id": customer_id,
            "amount": amount,
            "status": FailedPaymentStatus.OPEN.value,
        },
        sort=[("detected_at", -1)],
    )
    return FailedPaymentModel.from_mongo(document) if document else None


async def increment_retry_count(db: AsyncIOMotorDatabase, failed_payment_id) -> None:
    oid = _safe_object_id(failed_payment_id)
    if oid is None:
        return
    await db[_COLLECTION].update_one(
        {"_id": oid},
        {"$inc": {"retry_attempts_count": 1}, "$set": {"updated_at": datetime.now(timezone.utc)}},
    )


async def mark_recovered(db: AsyncIOMotorDatabase, failed_payment_id, recovered_amount: int) -> bool:
    oid = _safe_object_id(failed_payment_id)
    if oid is None:
        return False
    now = datetime.now(timezone.utc)
    result = await db[_COLLECTION].update_one(
        {"_id": oid, "status": FailedPaymentStatus.OPEN.value},
        {
            "$set": {
                "status": FailedPaymentStatus.RECOVERED.value,
                "recovered_amount": recovered_amount,
                "recovered_at": now,
                "updated_at": now,
            }
        },
    )
    return result.matched_count > 0


async def list_failed_payments(
    db: AsyncIOMotorDatabase,
    business_id,
    status=None,
    failure_reason_category: str | None = None,
    risk_tier: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    customer_email: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """
    Returns FailedPaymentListItem-shaped dicts, joined with the current
    (is_current=True) RecoveryPredictions document via $lookup, so the
    route layer never has to make a second query per case.
    """
    biz_oid = _safe_object_id(business_id)
    if biz_oid is None:
        return [], 0

    match: dict = {"business_id": biz_oid}
    if status:
        match["status"] = status.value if hasattr(status, "value") else status
    if failure_reason_category:
        match["failure_reason_category"] = failure_reason_category
    date_range = _date_to_range(from_date, to_date)
    if date_range:
        match["detected_at"] = date_range
    if customer_email:
        match["customer.email"] = customer_email

    pipeline: list[dict] = [
        {"$match": match},
        {
            "$lookup": {
                "from": _PREDICTIONS_COLLECTION,
                "let": {"fp_id": "$_id"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$failed_payment_id", "$$fp_id"]},
                                    {"$eq": ["$is_current", True]},
                                ]
                            }
                        }
                    },
                    {"$limit": 1},
                ],
                "as": "current_prediction",
            }
        },
        {
            "$addFields": {
                "recovery_score": {"$arrayElemAt": ["$current_prediction.recovery_score", 0]},
                "risk_tier": {"$arrayElemAt": ["$current_prediction.risk_tier", 0]},
            }
        },
    ]
    if risk_tier:
        pipeline.append({"$match": {"risk_tier": risk_tier}})

    count_pipeline = pipeline + [{"$count": "total"}]
    count_result = await db[_COLLECTION].aggregate(count_pipeline).to_list(length=1)
    total_items = count_result[0]["total"] if count_result else 0

    pipeline += [
        {"$sort": {"detected_at": -1}},
        {"$skip": (page - 1) * page_size},
        {"$limit": page_size},
    ]

    items: list[dict] = []
    async for doc in db[_COLLECTION].aggregate(pipeline):
        items.append(
            {
                "failed_payment_id": str(doc["_id"]),
                "customer": {"name": doc["customer"]["name"], "email": doc["customer"].get("email")},
                "amount": doc["amount"],
                "currency": doc["currency"],
                "failure_reason_category": doc["failure_reason_category"],
                "status": doc["status"],
                "recovery_score": doc.get("recovery_score"),
                "risk_tier": doc.get("risk_tier"),
                "retry_attempts_count": doc["retry_attempts_count"],
                "detected_at": doc["detected_at"],
            }
        )
    return items, total_items
