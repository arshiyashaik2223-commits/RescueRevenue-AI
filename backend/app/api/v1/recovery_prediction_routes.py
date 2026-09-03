"""
app/api/v1/recovery_prediction_routes.py
Recovery Prediction endpoints: Generate Recovery Score, Get Recovery
Recommendations. Implements Section D of the approved API spec.
"""
import logging

from fastapi import APIRouter, Depends, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from app.core.exceptions import AppError
from app.core.security import get_current_user, require_roles
from app.db.database import get_database
from app.db.repositories import failed_payments_repo
from app.models.recovery_prediction import RecoveryPredictionModel
from app.models.user import UserModel, UserRole
from app.services import recovery_prediction_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recovery-predictions", tags=["Recovery Predictions"])


class GenerateRecoveryScoreRequest(BaseModel):
    failed_payment_id: str = Field(..., min_length=1)
    force_recompute: bool = False


class RecommendedActionResponse(BaseModel):
    channel: str
    next_attempt_at: str
    cadence_step: int


class RecoveryPredictionResponse(BaseModel):
    prediction_id: str
    failed_payment_id: str
    recovery_score: float
    risk_tier: str
    model_version: str
    recommended_action: RecommendedActionResponse | None = None
    predicted_at: str

    @classmethod
    def from_model(cls, p: RecoveryPredictionModel) -> "RecoveryPredictionResponse":
        return cls(
            prediction_id=str(p.id),
            failed_payment_id=str(p.failed_payment_id),
            recovery_score=p.recovery_score,
            risk_tier=p.risk_tier.value,
            model_version=p.model_version,
            recommended_action=(
                RecommendedActionResponse(
                    channel=p.recommended_action.channel.value,
                    next_attempt_at=p.recommended_action.next_attempt_at.isoformat(),
                    cadence_step=p.recommended_action.cadence_step,
                )
                if p.recommended_action
                else None
            ),
            predicted_at=p.predicted_at.isoformat(),
        )


class RecoveryRecommendationResponse(BaseModel):
    failed_payment_id: str
    current_prediction: RecoveryPredictionResponse
    history: list[RecoveryPredictionResponse]


@router.post(
    "/generate",
    response_model=RecoveryPredictionResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate (or reuse) a recovery score for a failed payment",
)
async def generate_recovery_score(
    payload: GenerateRecoveryScoreRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: UserModel = Depends(require_roles(UserRole.ADMIN, UserRole.ANALYST)),
) -> RecoveryPredictionResponse:
    """
    Error responses:
      - 404 FAILED_PAYMENT_NOT_FOUND
      - 409 CASE_ALREADY_CLOSED
      - 500 MODEL_INFERENCE_FAILED
    """
    failed_payment = await failed_payments_repo.get_by_id(db, current_user.business_id, payload.failed_payment_id)
    if failed_payment is None:
        raise AppError(
            status_code=404, code="FAILED_PAYMENT_NOT_FOUND", message="No failed payment found with this ID."
        )

    try:
        prediction = await recovery_prediction_service.generate_recovery_score(
            db, failed_payment, force_recompute=payload.force_recompute
        )
    except recovery_prediction_service.CaseAlreadyClosedError as exc:
        raise AppError(
            status_code=409,
            code="CASE_ALREADY_CLOSED",
            message="Cannot generate a new prediction for a closed case.",
        ) from exc
    except recovery_prediction_service.ModelInferenceError as exc:
        raise AppError(
            status_code=500,
            code="MODEL_INFERENCE_FAILED",
            message="The recovery scoring model failed to produce a result.",
        ) from exc

    return RecoveryPredictionResponse.from_model(prediction)


@router.get(
    "/{failed_payment_id}",
    response_model=RecoveryRecommendationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get the current recovery recommendation for a failed payment",
)
async def get_recovery_recommendations(
    failed_payment_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: UserModel = Depends(get_current_user),
    include_history: bool = Query(default=False),
) -> RecoveryRecommendationResponse:
    """
    Error responses:
      - 404 FAILED_PAYMENT_NOT_FOUND
      - 404 PREDICTION_NOT_FOUND
    """
    failed_payment = await failed_payments_repo.get_by_id(db, current_user.business_id, failed_payment_id)
    if failed_payment is None:
        raise AppError(
            status_code=404, code="FAILED_PAYMENT_NOT_FOUND", message="No failed payment found with this ID."
        )

    try:
        current, history = await recovery_prediction_service.get_current_recommendation(
            db, failed_payment.id, include_history=include_history
        )
    except recovery_prediction_service.PredictionNotFoundError as exc:
        raise AppError(
            status_code=404,
            code="PREDICTION_NOT_FOUND",
            message="No prediction exists yet for this failed payment.",
        ) from exc

    return RecoveryRecommendationResponse(
        failed_payment_id=failed_payment_id,
        current_prediction=RecoveryPredictionResponse.from_model(current),
        history=[RecoveryPredictionResponse.from_model(h) for h in history],
    )
