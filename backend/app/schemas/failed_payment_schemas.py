"""
app/schemas/failed_payment_schemas.py
API-facing request/response schemas for Section C (Failed Payments).
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.models.failed_payment import FailedPaymentModel, FailedPaymentSourceType, FailureReasonCategory
from app.models.transaction import CustomerSnapshot


class FailedPaymentCreateRequest(BaseModel):
    transaction_id: str = Field(..., min_length=1)
    customer: CustomerSnapshot
    source_type: FailedPaymentSourceType
    amount: int = Field(..., gt=0)
    currency: str = Field(..., min_length=3, max_length=3)
    failure_reason_category: FailureReasonCategory
    raw_error_code: Optional[str] = None

    @model_validator(mode="after")
    def customer_must_have_contact(self) -> "FailedPaymentCreateRequest":
        if not self.customer.email and not self.customer.phone:
            raise ValueError("customer.email or customer.phone is required.")
        return self


class FailedPaymentResponse(BaseModel):
    """Minimal creation response per API spec C.1."""

    failed_payment_id: str
    status: str
    detected_at: datetime

    @classmethod
    def from_model(cls, fp: FailedPaymentModel) -> "FailedPaymentResponse":
        return cls(failed_payment_id=str(fp.id), status=fp.status.value, detected_at=fp.detected_at)


class CustomerSummary(BaseModel):
    name: str
    email: Optional[str] = None


class FailedPaymentListItem(BaseModel):
    failed_payment_id: str
    customer: CustomerSummary
    amount: int
    currency: str
    failure_reason_category: str
    status: str
    recovery_score: Optional[float] = None
    risk_tier: Optional[str] = None
    retry_attempts_count: int
    detected_at: datetime


class FailedPaymentListResponse(BaseModel):
    items: list[FailedPaymentListItem]
    page: int
    page_size: int
    total_items: int
    total_pages: int


class RetryPaymentRequest(BaseModel):
    notify_customer: bool = True


class RetryPaymentResponse(BaseModel):
    recovery_action_id: str
    failed_payment_id: str
    action_type: str
    status: str
    scheduled_at: datetime
