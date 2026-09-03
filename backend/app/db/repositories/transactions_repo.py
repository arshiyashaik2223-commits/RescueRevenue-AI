"""
app/db/repositories/transactions_repo.py
Data access layer for the Transactions collection.
"""
import logging
from datetime import date, datetime, time, timezone

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from app.models.transaction import TransactionCreate, TransactionModel, TransactionStatus, TransactionType

logger = logging.getLogger(__name__)

_COLLECTION = "transactions"


class DuplicateTransactionError(Exception):
    """Raised when a transaction with the same razorpay_payment_id already exists."""


def _safe_object_id(value):
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


def _date_to_range(from_date: date | None, to_date: date | None) -> dict:
    range_filter: dict = {}
    if from_date:
        range_filter["$gte"] = datetime.combine(from_date, time.min, tzinfo=timezone.utc)
    if to_date:
        range_filter["$lte"] = datetime.combine(to_date, time.max, tzinfo=timezone.utc)
    return range_filter


async def create_transaction(db: AsyncIOMotorDatabase, transaction: TransactionCreate) -> TransactionModel:
    document = transaction.model_dump()
    document["created_at"] = datetime.now(timezone.utc)
    try:
        result = await db[_COLLECTION].insert_one(document)
    except DuplicateKeyError as exc:
        raise DuplicateTransactionError(
            f"Transaction with razorpay_payment_id={transaction.razorpay_payment_id} already exists."
        ) from exc
    document["_id"] = result.inserted_id
    return TransactionModel.from_mongo(document)


async def get_by_id(db: AsyncIOMotorDatabase, business_id, transaction_id: str) -> TransactionModel | None:
    oid = _safe_object_id(transaction_id)
    biz_oid = _safe_object_id(business_id)
    if oid is None or biz_oid is None:
        return None
    document = await db[_COLLECTION].find_one({"_id": oid, "business_id": biz_oid})
    return TransactionModel.from_mongo(document) if document else None


async def get_by_razorpay_payment_id(
    db: AsyncIOMotorDatabase, business_id, razorpay_payment_id: str
) -> TransactionModel | None:
    biz_oid = _safe_object_id(business_id)
    if biz_oid is None:
        return None
    document = await db[_COLLECTION].find_one(
        {"business_id": biz_oid, "razorpay_payment_id": razorpay_payment_id}
    )
    return TransactionModel.from_mongo(document) if document else None


async def list_transactions(
    db: AsyncIOMotorDatabase,
    business_id,
    status: TransactionStatus | None = None,
    type: TransactionType | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    customer_email: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[TransactionModel], int]:
    biz_oid = _safe_object_id(business_id)
    if biz_oid is None:
        return [], 0

    query: dict = {"business_id": biz_oid}
    if status:
        query["status"] = status.value if hasattr(status, "value") else status
    if type:
        query["type"] = type.value if hasattr(type, "value") else type
    date_range = _date_to_range(from_date, to_date)
    if date_range:
        query["occurred_at"] = date_range
    if customer_email:
        query["customer.email"] = customer_email

    total_items = await db[_COLLECTION].count_documents(query)
    cursor = (
        db[_COLLECTION]
        .find(query)
        .sort("occurred_at", -1)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [TransactionModel.from_mongo(doc) async for doc in cursor]
    return items, total_items
