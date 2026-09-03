"""
app/models/recovery_prediction.py
Domain model for the RecoveryPredictions collection.
Reference: RevenueRescue-AI-Database-Schema.md, Section 4.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.user import PyObjectId


class RiskTier(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ActionChannel(str, Enum):
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    PAYMENT_RETRY = "payment_retry"


class RecommendedAction(BaseModel):
    channel: ActionChannel
    next_attempt_at: datetime
    cadence_step: int = Field(..., ge=1)


class RecoveryPredictionModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    business_id: PyObjectId
    failed_payment_id: PyObjectId
    recovery_score: float = Field(..., ge=0.0, le=1.0)
    risk_tier: RiskTier
    model_version: str
    features_used: dict[str, Any] = Field(default_factory=dict)
    recommended_action: Optional[RecommendedAction] = None
    is_current: bool = True
    predicted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_mongo(self) -> dict:
        data = self.model_dump(by_alias=True, exclude_none=False)
        if data.get("_id") is None:
            data.pop("_id", None)
        return data

    @classmethod
    def from_mongo(cls, document: dict) -> "RecoveryPredictionModel":
        return cls.model_validate(document)


class RecoveryPredictionCreate(BaseModel):
    business_id: PyObjectId
    failed_payment_id: PyObjectId
    recovery_score: float = Field(..., ge=0.0, le=1.0)
    risk_tier: RiskTier
    model_version: str
    features_used: dict[str, Any] = Field(default_factory=dict)
    recommended_action: Optional[RecommendedAction] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)
