"""
app/models/failed_payment.py

Domain model for the `FailedPayments` collection — the recovery-focused
collection derived from `Transactions` events where status = "failed"
(plus subscription billing failures). This is the collection the
recovery pipeline (RecoveryPredictions, RecoveryActions) actually
operates against, and the primary data source for the "recovery feed"
(GET /failed-payments) and retry (POST /failed-payments/{id}/retry)
endpoints in the approved API spec.

Reuses `CustomerSnapshot` from app/models/transaction.py — both
collections embed the identical point-in-time customer snapshot shape
per the schema doc's embedding rationale.

Reference: RevenueRescue-AI-Database-Schema.md, Section 3 ("FailedPayments").
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.transaction import CustomerSnapshot
from app.models.user import PyObjectId  # shared ObjectId type, see app/models/user.py


class FailedPaymentSourceType(str, Enum):
    """What triggered this failed-payment record."""

    PAYMENT_FAILED = "payment_failed"
    SUBSCRIPTION_FAILED = "subscription_failed"


class FailureReasonCategory(str, Enum):
    """
    Normalized failure-reason bucket, mapped from Razorpay's raw error
    codes during ingestion (see services/event_ingestion_service.py).
    Used throughout analytics (failure trends, copilot breakdowns) and
    as a feature input to the recovery-scoring model.
    """

    INSUFFICIENT_FUNDS = "insufficient_funds"
    CARD_EXPIRED = "card_expired"
    BANK_DECLINED = "bank_declined"
    RISK_BLOCKED = "risk_blocked"
    TIMEOUT = "timeout"
    OTHER = "other"


class FailedPaymentStatus(str, Enum):
    """Lifecycle status of the recovery case."""

    OPEN = "open"
    RECOVERED = "recovered"
    LOST = "lost"
    EXPIRED = "expired"


class FailedPaymentModel(BaseModel):
    """
    Full representation of a `FailedPayments` document as stored in
    MongoDB.

    Field-by-field mapping to the approved schema doc:
      _id                      -> id (aliased, ObjectId)
      business_id               -> business_id (ObjectId, FK -> businesses._id)
      transaction_id             -> transaction_id (ObjectId, FK -> Transactions._id)
      customer                   -> customer (embedded CustomerSnapshot, incl. timezone)
      source_type                 -> source_type (payment_failed | subscription_failed)
      amount                       -> amount (amount at risk, smallest currency unit)
      currency                      -> currency (ISO 4217)
      failure_reason_category        -> failure_reason_category (normalized bucket)
      raw_error_code                  -> raw_error_code (original Razorpay error code)
      retry_attempts_count              -> retry_attempts_count (default 0)
      status                              -> status (open | recovered | lost | expired)
      recovered_amount                     -> recovered_amount (set when status = recovered)
      recovered_at                          -> recovered_at (set when status = recovered)
      detected_at                            -> detected_at (when failure was first detected)
      updated_at                              -> updated_at (last status change)
    """

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    business_id: PyObjectId
    transaction_id: PyObjectId
    customer: CustomerSnapshot

    source_type: FailedPaymentSourceType
    amount: int = Field(..., gt=0, description="Amount at risk, smallest currency unit")
    currency: str = Field(..., min_length=3, max_length=3)

    failure_reason_category: FailureReasonCategory
    raw_error_code: Optional[str] = None

    retry_attempts_count: int = Field(default=0, ge=0)
    status: FailedPaymentStatus = FailedPaymentStatus.OPEN

    recovered_amount: Optional[int] = Field(default=None, ge=0)
    recovered_at: Optional[datetime] = None

    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_mongo(self) -> dict:
        """
        Serializes the model into a plain dict suitable for insertion into
        MongoDB via Motor, dropping `_id` when unset so MongoDB assigns it
        on insert.
        """
        data = self.model_dump(by_alias=True, exclude_none=False)
        if data.get("_id") is None:
            data.pop("_id", None)
        return data

    @classmethod
    def from_mongo(cls, document: dict) -> "FailedPaymentModel":
        """Builds a FailedPaymentModel from a raw MongoDB document."""
        return cls.model_validate(document)

    def mark_recovered(self, recovered_amount: int, recovered_at: Optional[datetime] = None) -> None:
        """
        Transitions this case to `recovered`, setting the amount and
        timestamp. Mutates in place; caller (services/event_ingestion_service.py,
        on observing a matching payment.captured event) is responsible for
        persisting the change via the repository.
        """
        self.status = FailedPaymentStatus.RECOVERED
        self.recovered_amount = recovered_amount
        self.recovered_at = recovered_at or datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def is_closed(self) -> bool:
        """
        True if this case is no longer open for recovery actions
        (recovered, lost, or expired) — used to guard against triggering
        further retries/messages on a closed case, per the API spec's
        409 CASE_ALREADY_CLOSED rule.
        """
        return self.status != FailedPaymentStatus.OPEN


class FailedPaymentCreate(BaseModel):
    """
    Shape needed to construct a new FailedPaymentModel before persistence —
    excludes `id`, `detected_at`, `updated_at`, `status`, `retry_attempts_count`,
    `recovered_amount`, and `recovered_at`, which are either DB-assigned,
    defaulted, or only ever set on later transitions.
    """

    business_id: PyObjectId
    transaction_id: PyObjectId
    customer: CustomerSnapshot
    source_type: FailedPaymentSourceType
    amount: int = Field(..., gt=0)
    currency: str = Field(..., min_length=3, max_length=3)
    failure_reason_category: FailureReasonCategory
    raw_error_code: Optional[str] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)
