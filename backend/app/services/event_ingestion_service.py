"""
app/services/event_ingestion_service.py
Normalizes an inbound Razorpay webhook payload into Transactions /
FailedPayments documents. Called from app.workers.tasks_ingestion.

Returns the new failed_payment_id (str) if a failure was detected and
recorded, so the calling task can chain into scoring — otherwise None.
"""
import logging
from datetime import datetime, timezone

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.repositories import failed_payments_repo, transactions_repo
from app.models.failed_payment import FailedPaymentCreate, FailedPaymentSourceType, FailureReasonCategory
from app.models.transaction import (
    CustomerSnapshot,
    PaymentMethod,
    TransactionCreate,
    TransactionStatus,
    TransactionType,
)

logger = logging.getLogger(__name__)

# Maps Razorpay's raw error codes/descriptions to our normalized buckets.
# v1: a small hand-curated mapping — extend as new Razorpay error codes
# are observed in production traffic.
_ERROR_CODE_MAP = {
    "BAD_REQUEST_ERROR": FailureReasonCategory.CARD_EXPIRED,
    "GATEWAY_ERROR": FailureReasonCategory.BANK_DECLINED,
    "SERVER_ERROR": FailureReasonCategory.TIMEOUT,
}


def _map_error_code(raw_code: str | None, description: str | None) -> FailureReasonCategory:
    if raw_code and raw_code in _ERROR_CODE_MAP:
        return _ERROR_CODE_MAP[raw_code]
    desc = (description or "").lower()
    if "insufficient" in desc:
        return FailureReasonCategory.INSUFFICIENT_FUNDS
    if "expired" in desc:
        return FailureReasonCategory.CARD_EXPIRED
    if "declined" in desc:
        return FailureReasonCategory.BANK_DECLINED
    if "timeout" in desc or "timed out" in desc:
        return FailureReasonCategory.TIMEOUT
    if "risk" in desc or "fraud" in desc:
        return FailureReasonCategory.RISK_BLOCKED
    return FailureReasonCategory.OTHER


def _extract_customer(entity: dict) -> CustomerSnapshot:
    notes = entity.get("notes", {}) or {}
    return CustomerSnapshot(
        customer_id=entity.get("customer_id") or entity.get("email") or "unknown",
        name=notes.get("customer_name", "Unknown Customer"),
        email=entity.get("email"),
        phone=entity.get("contact"),
    )


def _map_payment_method(method: str | None) -> PaymentMethod | None:
    if method is None:
        return None
    try:
        return PaymentMethod(method)
    except ValueError:
        return PaymentMethod.OTHER


async def ingest_razorpay_event(db: AsyncIOMotorDatabase, business_id: str, payload: dict) -> str | None:
    event_type = payload.get("event", "")
    biz_oid = ObjectId(business_id)

    if event_type == "payment.failed":
        return await _handle_payment_failed(db, biz_oid, payload)
    if event_type in ("payment.captured", "order.paid"):
        await _handle_payment_captured(db, biz_oid, payload)
        return None

    logger.info("Ignoring unhandled Razorpay event type=%s business_id=%s", event_type, business_id)
    return None


async def _handle_payment_failed(db: AsyncIOMotorDatabase, business_id: ObjectId, payload: dict) -> str | None:
    entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
    if not entity:
        logger.warning("payment.failed event missing payment entity, business_id=%s", business_id)
        return None

    customer = _extract_customer(entity)
    occurred_at = datetime.fromtimestamp(
        entity.get("created_at", datetime.now(timezone.utc).timestamp()), tz=timezone.utc
    )

    transaction_payload = TransactionCreate(
        business_id=business_id,
        customer=customer,
        razorpay_order_id=entity.get("order_id", ""),
        razorpay_payment_id=entity.get("id"),
        type=TransactionType.PAYMENT,
        status=TransactionStatus.FAILED,
        amount=entity.get("amount", 0),
        currency=entity.get("currency", "INR"),
        payment_method=_map_payment_method(entity.get("method")),
        error_code=entity.get("error_code"),
        error_reason=entity.get("error_description"),
        metadata={},
        raw_webhook_payload=payload,
        occurred_at=occurred_at,
    )

    try:
        transaction = await transactions_repo.create_transaction(db, transaction_payload)
    except transactions_repo.DuplicateTransactionError:
        logger.info("Duplicate payment.failed webhook delivery, payment_id=%s", entity.get("id"))
        return None

    existing = await failed_payments_repo.get_by_transaction_id(db, business_id, str(transaction.id))
    if existing:
        return None  # already processed (defensive; shouldn't happen given the dedup above)

    failed_payment = await failed_payments_repo.create_failed_payment(
        db,
        FailedPaymentCreate(
            business_id=business_id,
            transaction_id=transaction.id,
            customer=customer,
            source_type=FailedPaymentSourceType.PAYMENT_FAILED,
            amount=entity.get("amount", 0),
            currency=entity.get("currency", "INR"),
            failure_reason_category=_map_error_code(entity.get("error_code"), entity.get("error_description")),
            raw_error_code=entity.get("error_code"),
        ),
    )

    logger.info("FailedPayment created from webhook: id=%s business_id=%s", failed_payment.id, business_id)
    return str(failed_payment.id)


async def _handle_payment_captured(db: AsyncIOMotorDatabase, business_id: ObjectId, payload: dict) -> None:
    entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
    if not entity:
        return

    customer = _extract_customer(entity)
    occurred_at = datetime.fromtimestamp(
        entity.get("created_at", datetime.now(timezone.utc).timestamp()), tz=timezone.utc
    )

    transaction_payload = TransactionCreate(
        business_id=business_id,
        customer=customer,
        razorpay_order_id=entity.get("order_id", ""),
        razorpay_payment_id=entity.get("id"),
        type=TransactionType.PAYMENT,
        status=TransactionStatus.SUCCESS,
        amount=entity.get("amount", 0),
        currency=entity.get("currency", "INR"),
        payment_method=_map_payment_method(entity.get("method")),
        metadata={},
        raw_webhook_payload=payload,
        occurred_at=occurred_at,
    )

    try:
        await transactions_repo.create_transaction(db, transaction_payload)
    except transactions_repo.DuplicateTransactionError:
        logger.info("Duplicate payment.captured webhook delivery, payment_id=%s", entity.get("id"))

    # Reconciliation: if this successful payment matches an OPEN failed
    # payment for the same customer/amount, mark it recovered. See the
    # heuristic-matching caveat documented in
    # failed_payments_repo.get_open_by_customer_and_amount.
    matching_case = await failed_payments_repo.get_open_by_customer_and_amount(
        db, business_id, customer.customer_id, entity.get("amount", 0)
    )
    if matching_case:
        await failed_payments_repo.mark_recovered(db, matching_case.id, entity.get("amount", 0))
        logger.info("FailedPayment marked recovered: id=%s business_id=%s", matching_case.id, business_id)
