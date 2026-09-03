"""
app/services/recovery_prediction_service.py

Recovery Prediction service — orchestrates the recovery-probability
scoring pipeline for a failed payment: builds features, runs the model,
derives a risk tier, gets a recommended next action from the timing
engine, and persists a versioned RecoveryPredictions document.

Backs Section D of RevenueRescue-AI-API-Specification.md:
  - D.1 Generate Recovery Score  -> generate_recovery_score()
  - D.2 Get Recovery Recommendations -> get_current_recommendation()

Design notes:
  - Scoring and timing stay as separate concerns (feature/model logic
    here + in app/ml/, cadence/business-hours logic in
    app/services/retry_timing_service.py) per the original architecture
    doc's module separation — this service is the orchestrator that
    calls both and persists the combined result.
  - RecoveryPredictions documents are versioned, not overwritten: each
    call to generate_recovery_score() that actually recomputes creates
    a NEW document and flips the previous one's is_current to False,
    preserving a full audit trail (see database schema doc, Section 4).
  - Domain-specific failures are raised as typed exceptions
    (FailedPaymentNotFoundError, CaseAlreadyClosedError) rather than
    HTTP errors — the route layer (recovery_prediction_routes.py,
    upcoming) is responsible for translating these into the exact
    AppError/status codes from the API spec, keeping this service
    transport-agnostic and unit-testable in isolation.

Depends on (generated in upcoming files):
  - app.models.recovery_prediction : RecoveryPredictionModel,
                                      RecoveryPredictionCreate, RiskTier,
                                      RecommendedAction
  - app.db.repositories.recovery_predictions_repo : get_current,
                                      create_and_mark_current
  - app.ml.feature_engineering : build_features
  - app.ml.model_infer : predict
  - app.services.retry_timing_service : recommend_next_action
"""

import logging
from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import settings
from app.db.repositories import recovery_predictions_repo
from app.ml import feature_engineering, model_infer
from app.models.failed_payment import FailedPaymentModel
from app.models.recovery_prediction import (
    RecoveryPredictionCreate,
    RecoveryPredictionModel,
    RiskTier,
)
from app.services import retry_timing_service

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Domain exceptions
# ----------------------------------------------------------------------
class RecoveryPredictionError(Exception):
    """Base class for recovery-prediction domain errors."""


class FailedPaymentNotFoundError(RecoveryPredictionError):
    """Raised when the referenced failed payment does not exist for this business."""


class CaseAlreadyClosedError(RecoveryPredictionError):
    """Raised when attempting to score a case that is recovered/lost/expired."""


class PredictionNotFoundError(RecoveryPredictionError):
    """Raised when no prediction exists yet for a failed payment (D.2)."""


class ModelInferenceError(RecoveryPredictionError):
    """Raised when the scoring model fails to produce a result."""


# ----------------------------------------------------------------------
# Risk tier thresholds
# ----------------------------------------------------------------------
# NOTE: these are the v1 heuristic cutoffs referenced in the architecture
# doc's scoring_service description. They're intentionally centralized
# here as named constants (rather than scattered magic numbers) so they
# can be tuned or made business-configurable later without touching the
# scoring/persistence flow itself.
_HIGH_TIER_THRESHOLD = 0.66
_MEDIUM_TIER_THRESHOLD = 0.33


def _score_to_risk_tier(score: float) -> RiskTier:
    """Maps a raw 0.0-1.0 recovery_score to a coarse risk tier."""
    if score >= _HIGH_TIER_THRESHOLD:
        return RiskTier.HIGH
    if score >= _MEDIUM_TIER_THRESHOLD:
        return RiskTier.MEDIUM
    return RiskTier.LOW


# ----------------------------------------------------------------------
# D.1 Generate Recovery Score
# ----------------------------------------------------------------------
async def generate_recovery_score(
    db: AsyncIOMotorDatabase,
    failed_payment: FailedPaymentModel,
    force_recompute: bool = False,
) -> RecoveryPredictionModel:
    """
    Produces (or reuses) a recovery prediction for the given failed
    payment.

    Caching rule (per API spec D.1): if `force_recompute` is False and a
    current prediction already exists and is younger than
    settings.RECOVERY_PREDICTION_CACHE_MINUTES, that existing prediction
    is returned as-is instead of recomputing — this controls cost on the
    ML/feature-fetch pipeline for repeated dashboard/QA calls.

    Raises:
      CaseAlreadyClosedError: if failed_payment.status is not "open".
      ModelInferenceError: if the scoring model fails.
    """
    if failed_payment.is_closed():
        raise CaseAlreadyClosedError(
            f"Cannot generate a new prediction for closed case {failed_payment.id}."
        )

    if not force_recompute:
        existing = await recovery_predictions_repo.get_current(db, failed_payment.id)
        if existing is not None and _is_fresh(existing.predicted_at):
            logger.info(
                "Reusing fresh prediction for failed_payment_id=%s (predicted_at=%s)",
                failed_payment.id,
                existing.predicted_at,
            )
            return existing

    features = await feature_engineering.build_features(db, failed_payment)

    try:
        score, model_version = await model_infer.predict(features)
    except Exception as exc:  # noqa: BLE001 - deliberately broad: any model failure maps to one domain error
        logger.exception("Model inference failed for failed_payment_id=%s", failed_payment.id)
        raise ModelInferenceError(str(exc)) from exc

    risk_tier = _score_to_risk_tier(score)

    # Sequence step 1 for a freshly generated prediction on a case with no
    # prior actions; retry_timing_service is responsible for figuring out
    # the correct next step if this is a rescore mid-sequence.
    recommended_action = await retry_timing_service.recommend_next_action(
        db,
        failed_payment=failed_payment,
        recovery_score=score,
    )

    prediction = await recovery_predictions_repo.create_and_mark_current(
        db,
        RecoveryPredictionCreate(
            business_id=failed_payment.business_id,
            failed_payment_id=failed_payment.id,
            recovery_score=score,
            risk_tier=risk_tier,
            model_version=model_version,
            features_used=features,
            recommended_action=recommended_action,
        ),
    )

    logger.info(
        "Recovery prediction generated: failed_payment_id=%s score=%.2f tier=%s model=%s",
        failed_payment.id,
        score,
        risk_tier.value,
        model_version,
    )

    return prediction


# ----------------------------------------------------------------------
# D.2 Get Recovery Recommendations
# ----------------------------------------------------------------------
async def get_current_recommendation(
    db: AsyncIOMotorDatabase,
    failed_payment_id,
    include_history: bool = False,
) -> tuple[RecoveryPredictionModel, list[RecoveryPredictionModel]]:
    """
    Returns the current (is_current=True) prediction for a failed
    payment, plus its prior versions if `include_history` is True.

    Raises:
      PredictionNotFoundError: if no prediction has ever been generated
        for this failed payment (client should call D.1 first).
    """
    current = await recovery_predictions_repo.get_current(db, failed_payment_id)
    if current is None:
        raise PredictionNotFoundError(
            f"No prediction exists yet for failed_payment_id={failed_payment_id}."
        )

    history: list[RecoveryPredictionModel] = []
    if include_history:
        history = await recovery_predictions_repo.get_history(db, failed_payment_id)

    return current, history


def _is_fresh(predicted_at: datetime) -> bool:
    """
    True if `predicted_at` is within the configured recovery-prediction
    cache window (settings.RECOVERY_PREDICTION_CACHE_MINUTES).
    """
    cache_window = timedelta(minutes=settings.RECOVERY_PREDICTION_CACHE_MINUTES)
    now = datetime.now(timezone.utc)
    predicted_at_aware = predicted_at if predicted_at.tzinfo else predicted_at.replace(tzinfo=timezone.utc)
    return (now - predicted_at_aware) < cache_window
