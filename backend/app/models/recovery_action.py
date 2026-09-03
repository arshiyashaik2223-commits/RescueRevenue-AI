"""
app/models/recovery_action.py
Domain model for the RecoveryActions collection.
Reference: RevenueRescue-AI-Database-Schema.md, Section 5.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.recovery_prediction import ActionChannel
from app.models.user import PyObjectId


class ActionStatus(str, Enum):
    SCHEDULED = "scheduled"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class TriggeredBy(str, Enum):
    AUTO_ENGINE = "auto_engine"
    MANUAL_USER = "manual_user"


class ActionOutcome(str, Enum):
    OPENED = "opened"
    CLICKED = "clicked"
    BOUNCED = "bounced"
    PAYMENT_SUCCEEDED = "payment_succeeded"
    NO_RESPONSE = "no_response"


class MessageContent(BaseModel):
    channel: str
    subject: Optional[str] = None
    body: str
    ai_model_used: Optional[str] = None


class RecoveryActionModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    business_id: PyObjectId
    failed_payment_id: PyObjectId
    recovery_prediction_id: Optional[PyObjectId] = None
    action_type: ActionChannel
    sequence_step: int = Field(..., ge=1)
    scheduled_at: datetime
    executed_at: Optional[datetime] = None
    status: ActionStatus = ActionStatus.SCHEDULED
    triggered_by: TriggeredBy
    triggered_by_user_id: Optional[PyObjectId] = None
    message_content: Optional[MessageContent] = None
    outcome: Optional[ActionOutcome] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_mongo(self) -> dict:
        data = self.model_dump(by_alias=True, exclude_none=False)
        if data.get("_id") is None:
            data.pop("_id", None)
        return data

    @classmethod
    def from_mongo(cls, document: dict) -> "RecoveryActionModel":
        return cls.model_validate(document)


class RecoveryActionCreate(BaseModel):
    business_id: PyObjectId
    failed_payment_id: PyObjectId
    recovery_prediction_id: Optional[PyObjectId] = None
    action_type: ActionChannel
    sequence_step: int = Field(..., ge=1)
    scheduled_at: datetime
    triggered_by: TriggeredBy
    triggered_by_user_id: Optional[PyObjectId] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)
