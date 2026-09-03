"""
app/services/recovery_action_service.py
Orchestrates recovery-action creation and execution — the RecoveryActions
record creation and Celery enqueue behind POST /failed-payments/{id}/retry
(Section C.3). The retry-count-cap check itself lives in the route
(failed_payment_routes.py), since it's a pure read against
FailedPaymentModel.retry_attempts_count the route already has in hand.
"""
import logging
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.repositories import recovery_actions_repo
from app.models.failed_payment import FailedPaymentModel
from app.models.recovery_action import ActionChannel, RecoveryActionCreate, RecoveryActionModel, TriggeredBy

logger = logging.getLogger(__name__)


class RazorpayRetryError(Exception):
    """Raised when creating/enqueueing a retry action fails."""


async def trigger_manual_retry(
    db: AsyncIOMotorDatabase,
    failed_payment: FailedPaymentModel,
    triggered_by_user_id,
    notify_customer: bool = True,
) -> RecoveryActionModel:
    """
    Creates a RecoveryActions record for an on-demand retry and enqueues
    the actual Razorpay call to a Celery worker
    (app.workers.tasks_notifications.execute_recovery_action) — the
    route returns 202 Accepted immediately per the API spec; the retry
    itself, and any resulting status change, happens asynchronously.
    """
    from app.db.repositories import recovery_predictions_repo  # local import: avoids a
    # circular dependency at module load time between this service and
    # the prediction repo, which is itself imported by
    # recovery_prediction_service.

    sequence_step = await recovery_actions_repo.count_for_failed_payment(db, failed_payment.id) + 1
    current_prediction = await recovery_predictions_repo.get_current(db, failed_payment.id)

    action = await recovery_actions_repo.create_recovery_action(
        db,
        RecoveryActionCreate(
            business_id=failed_payment.business_id,
            failed_payment_id=failed_payment.id,
            recovery_prediction_id=current_prediction.id if current_prediction else None,
            action_type=ActionChannel.PAYMENT_RETRY,
            sequence_step=sequence_step,
            scheduled_at=datetime.now(timezone.utc),
            triggered_by=TriggeredBy.MANUAL_USER,
            triggered_by_user_id=triggered_by_user_id,
        ),
    )

    try:
        # Imported here to avoid a hard import-time dependency on Celery
        # for callers (e.g. unit tests) that don't need the worker wired up.
        from app.workers import tasks_notifications

        tasks_notifications.execute_recovery_action.delay(
            recovery_action_id=str(action.id), notify_customer=notify_customer
        )
    except Exception as exc:  # noqa: BLE001 - broker/connection failures, etc.
        logger.exception("Failed to enqueue retry action_id=%s", action.id)
        raise RazorpayRetryError(str(exc)) from exc

    return action
