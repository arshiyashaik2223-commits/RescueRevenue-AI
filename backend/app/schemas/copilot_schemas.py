"""
app/schemas/copilot_schemas.py
API-facing request/response schemas for Section E (AI Copilot).
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.ai_insight import AIInsightModel


class AskQuestionRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)


class ChartData(BaseModel):
    type: str
    labels: list[str]
    series: list[float]


class AskQuestionResponse(BaseModel):
    insight_id: str
    question: str
    answer: str
    chart_data: Optional[ChartData] = None
    model_used: str
    created_at: datetime

    @classmethod
    def from_model(cls, insight: AIInsightModel, chart_data: Optional[ChartData] = None) -> "AskQuestionResponse":
        return cls(
            insight_id=str(insight.id),
            question=insight.question,
            answer=insight.answer,
            chart_data=chart_data,
            model_used=insight.model_used,
            created_at=insight.created_at,
        )


class AskedBy(BaseModel):
    user_id: str
    name: str


class InsightListItem(BaseModel):
    insight_id: str
    question: str
    answer: str
    asked_by: AskedBy
    created_at: datetime


class InsightListResponse(BaseModel):
    items: list[InsightListItem]
    page: int
    page_size: int
    total_items: int
    total_pages: int
