"""
app/models/transaction.py

Domain model for the `Transactions` collection — the complete ledger of
payment attempts (success or failure) and abandoned checkouts processed
through Razorpay for a business.

This is the DB-facing representation used by `app/db/repositories/
transactions_repo.py`. It is populated primarily by
`app/services/event_ingestion_service.py` off incoming Razorpay webhook
events, and secondarily via the manual `POST /transactions` endpoint for
backfill/reconciliation (per the approved API spec, Section B.1).

Reference: RevenueRescue-AI-Database-Schema.md, Section 2 ("Transactions").
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.user import PyObjectId  # shared ObjectId type, see app/models/user.py


class TransactionType(str, Enum):
    """What kind of event this transaction record represents."""

    PAYMENT = "payment"
    CHECKOUT_ABANDONED = "checkout_abandoned"
    INVOICE = "invoice"
    SUBSCRIPTION_CHARGE = "subscription_charge"


class TransactionStatus(str, Enum):
    """Outcome status of the transaction event."""

    SUCCESS = "success"
    FAILED = "failed"
    ABANDONED = "abandoned"
    PENDING = "pending"


class PaymentMethod(str, Enum):
    """Razorpay payment method used, when applicable."""

    CARD = "card"
    UPI = "upi"
    NETBANKING = "netbanking"
    WALLET = "wallet"
    EMI = "emi"
    OTHER = "other"


class CustomerSnapshot(BaseModel):
    """
    Point-in-time snapshot of the end-customer at the moment this
    transaction occurred — deliberately embedded rather than referenced,
    so historical records stay accurate even if the customer's profile
    (email, phone, name) changes later. Reused identically in the
    `FailedPayments` model (see app/models/failed_payment.py).

    `customer_id` is a logical identifier (not a hard FK) that lets
    records for the same real-world customer be correlated across
    documents without requiring a separate `customers` collection.
    """

    customer_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=120)
    email: Optional[str] = None
    phone: Optional[str] = None
    timezone: Optional[str] = None  # e.g. "Asia/Kolkata" — present on FailedPayments, optional here

    model_config = ConfigDict(extra="ignore")


class TransactionModel(BaseModel):
    """
    Full representation of a `Transactions` document as stored in MongoDB.

    Field-by-field mapping to the approved schema doc:
      _id                  -> id (aliased, ObjectId)
      business_id          -> business_id (ObjectId, FK -> businesses._id)
      customer              -> customer (embedded CustomerSnapshot)
      razorpay_order_id     -> razorpay_order_id
      razorpay_payment_id   -> razorpay_payment_id (present once a payment attempt exists)
      type                  -> type (payment | checkout_abandoned | invoice | subscription_charge)
      status                -> status (success | failed | abandoned | pending)
      amount                -> amount (smallest currency unit, e.g. paise)
      currency              -> currency (ISO 4217)
      payment_method        -> payment_method
      error_code            -> error_code (present only when status = failed)
      error_reason          -> error_reason
      metadata              -> metadata (free-form)
      raw_webhook_payload   -> raw_webhook_payload (full original Razorpay payload, for audit)
      occurred_at           -> occurred_at (when the event happened per Razorpay)
      created_at            -> created_at (when we recorded it)
    """

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        json_encoders={},
    )

    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    business_id: PyObjectId
    customer: CustomerSnapshot

    razorpay_order_id: str = Field(..., min_length=1)
    razorpay_payment_id: Optional[str] = None

    type: TransactionType
    status: TransactionStatus

    amount: int = Field(..., gt=0, description="Amount in smallest currency unit (e.g. paise)")
    currency: str = Field(..., min_length=3, max_length=3)
    payment_method: Optional[PaymentMethod] = None

    error_code: Optional[str] = None
    error_reason: Optional[str] = None

    metadata: dict[str, Any] = Field(default_factory=dict)
    raw_webhook_payload: Optional[dict[str, Any]] = None

    occurred_at: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

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
    def from_mongo(cls, document: dict) -> "TransactionModel":
        """Builds a TransactionModel from a raw MongoDB document."""
        return cls.model_validate(document)


class TransactionCreate(BaseModel):
    """
    Shape needed to construct a new TransactionModel before persistence —
    excludes `id` and `created_at`, which are assigned at creation time.
    Used by both the webhook ingestion path and the manual
    `POST /transactions` endpoint.
    """

    business_id: PyObjectId
    customer: CustomerSnapshot
    razorpay_order_id: str = Field(..., min_length=1)
    razorpay_payment_id: Optional[str] = None
    type: TransactionType
    status: TransactionStatus
    amount: int = Field(..., gt=0)
    currency: str = Field(..., min_length=3, max_length=3)
    payment_method: Optional[PaymentMethod] = None
    error_code: Optional[str] = None
    error_reason: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw_webhook_payload: Optional[dict[str, Any]] = None
    occurred_at: datetime

    model_config = ConfigDict(arbitrary_types_allowed=True)
