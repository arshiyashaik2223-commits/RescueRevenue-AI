"""
app/models/ai_insight.py
Domain model for the AIInsights collection.
Reference: RevenueRescue-AI-Database-Schema.md, Section 6.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.user import PyObjectId


class InsightFeedback(str, Enum):
    HELPFUL = "helpful"
    NOT_HELPFUL = "not_helpful"


class AIInsightModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    business_id: PyObjectId
    user_id: PyObjectId
    question: str
    question_hash: str
    answer: str
    tool_calls_made: list[dict[str, Any]] = Field(default_factory=list)
    data_snapshot_ref: dict[str, Any] = Field(default_factory=dict)
    model_used: str
    feedback: Optional[InsightFeedback] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_at: Optional[datetime] = None

    def to_mongo(self) -> dict:
        data = self.model_dump(by_alias=True, exclude_none=False)
        if data.get("_id") is None:
            data.pop("_id", None)
        return data

    @classmethod
    def from_mongo(cls, document: dict) -> "AIInsightModel":
        return cls.model_validate(document)


class AIInsightCreate(BaseModel):
    business_id: PyObjectId
    user_id: PyObjectId
    question: str
    question_hash: str
    answer: str
    tool_calls_made: list[dict[str, Any]] = Field(default_factory=list)
    data_snapshot_ref: dict[str, Any] = Field(default_factory=dict)
    model_used: str
    ttl_at: Optional[datetime] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)
