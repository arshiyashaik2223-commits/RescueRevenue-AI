"""
app/api/v1/transaction_routes.py

Transaction endpoints: Create Transaction, Get Transaction, List Transactions.
Implements Section B of RevenueRescue-AI-API-Specification.md exactly —
URLs, request/response shapes, validation rules, and error codes below
all mirror that document.

Note: in normal operation, Transactions are created automatically by the
Razorpay webhook handler (app/api/v1/webhook_routes.py, via
app/services/event_ingestion_service.py) — POST /transactions here exists
for manual entry, backfill, and reconciliation, per the API spec's note
on B.1.

Depends on (generated in upcoming files):
  - app.schemas.transaction_schemas : TransactionCreateRequest,
                                       TransactionResponse,
                                       TransactionListResponse,
                                       TransactionListQuery
  - app.db.repositories.transactions_repo : create_transaction, get_by_id,
                                       list_transactions,
                                       get_by_razorpay_payment_id
  - app.core.security : get_current_user, require_roles
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.exceptions import AppError
from app.core.security import get_current_user, require_roles
from app.db.database import get_database
from app.db.repositories import transactions_repo
from app.models.transaction import TransactionCreate, TransactionStatus, TransactionType
from app.models.user import UserModel, UserRole
from app.schemas.transaction_schemas import (
    TransactionCreateRequest,
    TransactionListResponse,
    TransactionResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transactions", tags=["Transactions"])


# ----------------------------------------------------------------------
# B.1 Create Transaction
# ----------------------------------------------------------------------
@router.post(
    "",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Manually record a transaction (backfill / reconciliation)",
)
async def create_transaction(
    payload: TransactionCreateRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN, UserRole.ANALYST)),
) -> TransactionResponse:
    """
    Validation (enforced partly by TransactionCreateRequest's Pydantic
    validators, partly here):
      - customer.email or customer.phone: at least one required
        (enforced in schema's model_validator)
      - razorpay_payment_id required if type == "payment" and
        status != "abandoned" (enforced here, since it's a cross-field
        rule best expressed against the resolved enum values)
      - occurred_at must not be in the future (enforced in schema)

    Error responses:
      - 409 DUPLICATE_PAYMENT_ID : razorpay_payment_id already exists
      - 422 VALIDATION_ERROR     : schema-level validation failures
      - 403 FORBIDDEN            : caller role is viewer (enforced by require_roles)
    """
    if (
        payload.type == TransactionType.PAYMENT
        and payload.status != TransactionStatus.ABANDONED
        and not payload.razorpay_payment_id
    ):
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message="razorpay_payment_id is required for non-abandoned payment transactions.",
            details={"razorpay_payment_id": "This field is required for the given type/status."},
        )

    if payload.razorpay_payment_id:
        existing = await transactions_repo.get_by_razorpay_payment_id(
            db, current_user.business_id, payload.razorpay_payment_id
        )
        if existing is not None:
            raise AppError(
                status_code=status.HTTP_409_CONFLICT,
                code="DUPLICATE_PAYMENT_ID",
                message="A transaction with this razorpay_payment_id already exists.",
            )

    transaction = await transactions_repo.create_transaction(
        db,
        TransactionCreate(
            business_id=current_user.business_id,
            customer=payload.customer,
            razorpay_order_id=payload.razorpay_order_id,
            razorpay_payment_id=payload.razorpay_payment_id,
            type=payload.type,
            status=payload.status,
            amount=payload.amount,
            currency=payload.currency,
            payment_method=payload.payment_method,
            metadata=payload.metadata or {},
            occurred_at=payload.occurred_at,
        ),
    )

    logger.info(
        "Transaction created: id=%s business_id=%s status=%s",
        transaction.id,
        current_user.business_id,
        transaction.status.value,
    )

    return TransactionResponse.from_model(transaction)


# ----------------------------------------------------------------------
# B.2 Get Transaction
# ----------------------------------------------------------------------
@router.get(
    "/{transaction_id}",
    response_model=TransactionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a single transaction by ID",
)
async def get_transaction(
    transaction_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: UserModel = Depends(get_current_user),
) -> TransactionResponse:
    """
    Error responses:
      - 404 TRANSACTION_NOT_FOUND : no matching transaction for this
        business (cross-tenant lookups are indistinguishable from "not found")
      - 422 VALIDATION_ERROR      : transaction_id is not a valid ObjectId
        (raised inside the repo/PyObjectId validation and surfaced here)
    """
    transaction = await transactions_repo.get_by_id(db, current_user.business_id, transaction_id)
    if transaction is None:
        raise AppError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="TRANSACTION_NOT_FOUND",
            message="No transaction found with this ID.",
        )
    return TransactionResponse.from_model(transaction)


# ----------------------------------------------------------------------
# B.3 List Transactions
# ----------------------------------------------------------------------
@router.get(
    "",
    response_model=TransactionListResponse,
    status_code=status.HTTP_200_OK,
    summary="List / filter transactions",
)
async def list_transactions(
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: UserModel = Depends(get_current_user),
    status_filter: TransactionStatus | None = Query(default=None, alias="status"),
    type_filter: TransactionType | None = Query(default=None, alias="type"),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    customer_email: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> TransactionListResponse:
    """
    Query params map directly to the approved API spec's table for B.3.

    Error responses:
      - 422 VALIDATION_ERROR : invalid enum filter value (handled by FastAPI/
        Pydantic enum coercion), page_size > 100 (handled by Query le=100),
        or from_date > to_date (checked explicitly below)
    """
    if from_date and to_date and from_date > to_date:
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message="from_date must not be after to_date.",
            details={"from_date": "Must be <= to_date."},
        )

    items, total_items = await transactions_repo.list_transactions(
        db,
        business_id=current_user.business_id,
        status=status_filter,
        type=type_filter,
        from_date=from_date,
        to_date=to_date,
        customer_email=customer_email,
        page=page,
        page_size=page_size,
    )

    total_pages = max(1, (total_items + page_size - 1) // page_size)

    return TransactionListResponse(
        items=[TransactionResponse.from_model(t) for t in items],
        page=page,
        page_size=page_size,
        total_items=total_items,
        total_pages=total_pages,
    )
