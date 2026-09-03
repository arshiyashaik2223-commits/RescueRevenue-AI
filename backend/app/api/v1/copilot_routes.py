"""
app/api/v1/copilot_routes.py
AI Copilot endpoints: Ask a Business Question, Get AI Insights.
Implements Section E of the approved API spec.
"""
import logging

from fastapi import APIRouter, Depends, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.exceptions import AppError
from app.core.security import get_current_user
from app.db.database import get_database
from app.db.repositories import ai_insights_repo
from app.models.user import UserModel, UserRole
from app.schemas.copilot_schemas import (
    AskedBy,
    AskQuestionRequest,
    AskQuestionResponse,
    ChartData,
    InsightListItem,
    InsightListResponse,
)
from app.services import copilot_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/copilot", tags=["AI Copilot"])


@router.post(
    "/ask",
    response_model=AskQuestionResponse,
    status_code=status.HTTP_200_OK,
    summary="Ask the AI Copilot a natural-language business question",
)
async def ask_question(
    payload: AskQuestionRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: UserModel = Depends(get_current_user),
) -> AskQuestionResponse:
    """
    Error responses:
      - 422 VALIDATION_ERROR : question too short/long (enforced by schema)
      - 502 CLAUDE_API_ERROR : the AI service call failed
    """
    try:
        insight, chart_data = await copilot_service.ask_question(
            db, current_user.business_id, current_user.id, payload.question
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Copilot ask_question failed")
        raise AppError(
            status_code=502, code="CLAUDE_API_ERROR", message="The AI service is temporarily unavailable."
        ) from exc

    return AskQuestionResponse.from_model(insight, ChartData(**chart_data) if chart_data else None)


@router.get(
    "/insights",
    response_model=InsightListResponse,
    status_code=status.HTTP_200_OK,
    summary="Get past Copilot Q&A history",
)
async def get_insights(
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: UserModel = Depends(get_current_user),
    user_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> InsightListResponse:
    """
    `user_id` filter is only honored for admins (per API spec E.2);
    non-admins are always scoped to their own questions regardless of
    what they pass.
    """
    effective_user_id = user_id if (user_id and current_user.role == UserRole.ADMIN) else str(current_user.id)

    items, total_items = await ai_insights_repo.list_insights(
        db, business_id=current_user.business_id, user_id=effective_user_id, page=page, page_size=page_size
    )
    total_pages = max(1, (total_items + page_size - 1) // page_size)

    return InsightListResponse(
        items=[
            InsightListItem(
                insight_id=str(i.id),
                question=i.question,
                answer=i.answer,
                asked_by=AskedBy(
                    user_id=str(i.user_id),
                    name=current_user.name if str(i.user_id) == str(current_user.id) else "Team member",
                ),
                created_at=i.created_at,
            )
            for i in items
        ],
        page=page,
        page_size=page_size,
        total_items=total_items,
        total_pages=total_pages,
    )
