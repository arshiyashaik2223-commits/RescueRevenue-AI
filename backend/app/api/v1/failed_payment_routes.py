"""
app/api/v1/failed_payment_routes.py

Failed Payment endpoints: Record Failed Payment, Get Failed Payments,
Retry Payment.
Implements Section C of RevenueRescue-AI-API-Specification.md exactly —
URLs, request/response shapes, validation rules, and error codes below
all mirror that document.

Note: in normal operation, FailedPayments records are created
automatically by the ingestion pipeline whenever a Transactions record
lands with status = "failed" (see app/services/event_ingestion_service.py).
POST /failed-payments here exists for manual entry/testing, mirroring
the same rationale as POST /transactions.

Depends on (generated in upcoming files):
  - app.schemas.failed_payment_schemas : FailedPaymentCreateRequest,
                                          FailedPaymentResponse,
                                          FailedPaymentListResponse,
                                          RetryPaymentRequest,
                                          RetryPaymentResponse
  - app.db.repositories.failed_payments_repo : create_failed_payment,
                                          get_by_id, get_by_transaction_id,
                                          list_failed_payments
  - app.db.repositories.transactions_repo : get_by_id (already used in
                                          transaction_routes.py)
  - app.services.recovery_action_service : trigger_manual_retry
                                          (owns the retry-limit check,
                                          RecoveryActions creation, and
                                          Celery task enqueue)
  - app.core.security : get_current_user, require_roles
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import settings
from app.core.exceptions import AppError
from app.core.security import get_current_user, require_roles
from app.db.database import get_database
from app.db.repositories import failed_payments_repo, transactions_repo
from app.models.failed_payment import FailedPaymentCreate, FailedPaymentStatus
from app.models.transaction import TransactionStatus
from app.models.user import UserModel, UserRole
from app.schemas.failed_payment_schemas import (
    FailedPaymentCreateRequest,
    FailedPaymentListResponse,
    FailedPaymentResponse,
    RetryPaymentRequest,
    RetryPaymentResponse,
)
from app.services import recovery_action_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/failed-payments", tags=["Failed Payments"])


# ----------------------------------------------------------------------
# C.1 Record Failed Payment
# ----------------------------------------------------------------------
@router.post(
    "",
    response_model=FailedPaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Manually record a failed payment (backfill / testing)",
)
async def record_failed_payment(
    payload: FailedPaymentCreateRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN, UserRole.ANALYST)),
) -> FailedPaymentResponse:
    """
    Validation (partly enforced by FailedPaymentCreateRequest's Pydantic
    validators, partly here):
      - transaction_id must reference an existing Transactions document
        belonging to this business AND that document's status must be
        "failed" (-> 404 / 422 below)
      - customer.email or customer.phone: at least one required
        (enforced in schema's model_validator)
      - amount > 0, enums valid (enforced by schema)

    Error responses:
      - 404 TRANSACTION_NOT_FOUND        : referenced transaction does not exist
      - 409 FAILED_PAYMENT_ALREADY_EXISTS: a FailedPayments record already
                                            exists for this transaction_id
      - 422 VALIDATION_ERROR             : referenced transaction's status
                                            is not "failed", or schema errors
    """
    transaction = await transactions_repo.get_by_id(
        db, current_user.business_id, payload.transaction_id
    )
    if transaction is None:
        raise AppError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="TRANSACTION_NOT_FOUND",
            message="Referenced transaction does not exist.",
        )

    if transaction.status != TransactionStatus.FAILED:
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message="Referenced transaction's status is not 'failed'.",
            details={"transaction_id": "Transaction status must be 'failed' to record a failed payment."},
        )

    existing = await failed_payments_repo.get_by_transaction_id(
        db, current_user.business_id, payload.transaction_id
    )
    if existing is not None:
        raise AppError(
            status_code=status.HTTP_409_CONFLICT,
            code="FAILED_PAYMENT_ALREADY_EXISTS",
            message="A failed payment record already exists for this transaction.",
        )

    failed_payment = await failed_payments_repo.create_failed_payment(
        db,
        FailedPaymentCreate(
            business_id=current_user.business_id,
            transaction_id=payload.transaction_id,
            customer=payload.customer,
            source_type=payload.source_type,
            amount=payload.amount,
            currency=payload.currency,
            failure_reason_category=payload.failure_reason_category,
            raw_error_code=payload.raw_error_code,
        ),
    )

    logger.info(
        "FailedPayment recorded: id=%s business_id=%s transaction_id=%s",
        failed_payment.id,
        current_user.business_id,
        payload.transaction_id,
    )

    return FailedPaymentResponse.from_model(failed_payment)


# ----------------------------------------------------------------------
# C.2 Get Failed Payments
# ----------------------------------------------------------------------
@router.get(
    "",
    response_model=FailedPaymentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List / filter failed payments (the recovery feed)",
)
async def get_failed_payments(
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: UserModel = Depends(get_current_user),
    status_filter: FailedPaymentStatus | None = Query(default=None, alias="status"),
    failure_reason_category: str | None = Query(default=None),
    risk_tier: str | None = Query(default=None),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    customer_email: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> FailedPaymentListResponse:
    """
    Query params map directly to the approved API spec's table for C.2.
    `risk_tier` and the returned `recovery_score` are joined in from the
    current (is_current=True) RecoveryPredictions document per case —
    handled inside failed_payments_repo.list_failed_payments via an
    aggregation pipeline, not duplicated here.

    Error responses:
      - 422 VALIDATION_ERROR : invalid filter enum, bad date range,
        page_size > 100
    """
    if from_date and to_date and from_date > to_date:
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message="from_date must not be after to_date.",
            details={"from_date": "Must be <= to_date."},
        )

    if risk_tier is not None and risk_tier not in ("high", "medium", "low"):
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message="risk_tier must be one of: high, medium, low.",
            details={"risk_tier": risk_tier},
        )

    items, total_items = await failed_payments_repo.list_failed_payments(
        db,
        business_id=current_user.business_id,
        status=status_filter,
        failure_reason_category=failure_reason_category,
        risk_tier=risk_tier,
        from_date=from_date,
        to_date=to_date,
        customer_email=customer_email,
        page=page,
        page_size=page_size,
    )

    total_pages = max(1, (total_items + page_size - 1) // page_size)

    return FailedPaymentListResponse(
        items=items,  # repo already returns list of FailedPaymentResponse-shaped dicts (incl. joined score/tier)
        page=page,
        page_size=page_size,
        total_items=total_items,
        total_pages=total_pages,
    )


# ----------------------------------------------------------------------
# C.3 Retry Payment
# ----------------------------------------------------------------------
@router.post(
    "/{failed_payment_id}/retry",
    response_model=RetryPaymentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger an on-demand payment retry for a failed payment",
)
async def retry_payment(
    failed_payment_id: str,
    payload: RetryPaymentRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN, UserRole.ANALYST)),
) -> RetryPaymentResponse:
    """
    202 Accepted rather than 200/201: the actual retry against Razorpay
    happens asynchronously via the worker queue (see
    app/workers/tasks_notifications.py, upcoming) — this response only
    confirms the retry was accepted/queued.

    Validation:
      - failed_payment_id must exist, belong to this business, and have
        status == "open" (-> 404 / 409 below)
      - retry_attempts_count must be below settings.RETRY_ATTEMPTS_MAX_PER_CASE
        (-> 429 below)

    Error responses:
      - 404 FAILED_PAYMENT_NOT_FOUND : no open failed payment with this ID
      - 409 CASE_ALREADY_CLOSED      : case is recovered/lost/expired
      - 429 RETRY_LIMIT_EXCEEDED     : retry cap reached for this case
      - 502 RAZORPAY_RETRY_FAILED    : Razorpay rejected the retry call itself
                                        (surfaced only if the synchronous
                                        portion of the call fails immediately;
                                        async failures are reflected later on
                                        the RecoveryActions record's status)
    """
    failed_payment = await failed_payments_repo.get_by_id(
        db, current_user.business_id, failed_payment_id
    )
    if failed_payment is None:
        raise AppError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="FAILED_PAYMENT_NOT_FOUND",
            message="No open failed payment found with this ID.",
        )

    if failed_payment.is_closed():
        raise AppError(
            status_code=status.HTTP_409_CONFLICT,
            code="CASE_ALREADY_CLOSED",
            message="This failed payment is already recovered, lost, or expired.",
        )

    if failed_payment.retry_attempts_count >= settings.RETRY_ATTEMPTS_MAX_PER_CASE:
        raise AppError(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="RETRY_LIMIT_EXCEEDED",
            message="Maximum retry attempts reached for this payment.",
        )

    try:
        recovery_action = await recovery_action_service.trigger_manual_retry(
            db,
            failed_payment=failed_payment,
            triggered_by_user_id=current_user.id,
            notify_customer=payload.notify_customer,
        )
    except recovery_action_service.RazorpayRetryError as exc:
        raise AppError(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="RAZORPAY_RETRY_FAILED",
            message="Razorpay was unable to process the retry.",
        ) from exc

    logger.info(
        "Manual retry triggered: failed_payment_id=%s recovery_action_id=%s user_id=%s",
        failed_payment_id,
        recovery_action.id,
        current_user.id,
    )

    return RetryPaymentResponse(
        recovery_action_id=str(recovery_action.id),
        failed_payment_id=failed_payment_id,
        action_type=recovery_action.action_type.value,
        status=recovery_action.status.value,
        scheduled_at=recovery_action.scheduled_at,
    )
