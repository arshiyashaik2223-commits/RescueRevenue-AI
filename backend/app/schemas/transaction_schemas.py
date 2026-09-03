"""
app/schemas/transaction_schemas.py
API-facing request/response schemas for Section B (Transactions).
"""
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.transaction import (
    CustomerSnapshot,
    PaymentMethod,
    TransactionModel,
    TransactionStatus,
    TransactionType,
)


class TransactionCreateRequest(BaseModel):
    customer: CustomerSnapshot
    razorpay_order_id: str = Field(..., min_length=1)
    razorpay_payment_id: Optional[str] = None
    type: TransactionType
    status: TransactionStatus
    amount: int = Field(..., gt=0)
    currency: str = Field(..., min_length=3, max_length=3)
    payment_method: Optional[PaymentMethod] = None
    metadata: dict[str, Any] | None = None
    occurred_at: datetime

    @model_validator(mode="after")
    def customer_must_have_contact(self) -> "TransactionCreateRequest":
        if not self.customer.email and not self.customer.phone:
            raise ValueError("customer.email or customer.phone is required.")
        return self

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_not_in_future(cls, v: datetime) -> datetime:
        now = datetime.now(timezone.utc)
        v_aware = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        if v_aware > now:
            raise ValueError("occurred_at must not be in the future.")
        return v


class TransactionResponse(BaseModel):
    transaction_id: str
    business_id: str
    customer: CustomerSnapshot
    razorpay_order_id: str
    razorpay_payment_id: Optional[str] = None
    type: TransactionType
    status: TransactionStatus
    amount: int
    currency: str
    payment_method: Optional[PaymentMethod] = None
    error_code: Optional[str] = None
    error_reason: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime
    created_at: datetime

    @classmethod
    def from_model(cls, t: TransactionModel) -> "TransactionResponse":
        return cls(
            transaction_id=str(t.id),
            business_id=str(t.business_id),
            customer=t.customer,
            razorpay_order_id=t.razorpay_order_id,
            razorpay_payment_id=t.razorpay_payment_id,
            type=t.type,
            status=t.status,
            amount=t.amount,
            currency=t.currency,
            payment_method=t.payment_method,
            error_code=t.error_code,
            error_reason=t.error_reason,
            metadata=t.metadata,
            occurred_at=t.occurred_at,
            created_at=t.created_at,
        )


class TransactionListResponse(BaseModel):
    items: list[TransactionResponse]
    page: int
    page_size: int
    total_items: int
    total_pages: int
