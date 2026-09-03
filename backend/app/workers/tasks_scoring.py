"""
app/workers/tasks_scoring.py
Celery task: runs recovery scoring for a newly created (or rescored)
failed payment, then schedules the first automated recovery action
based on the resulting recommendation.
"""
import asyncio
import logging

from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _get_worker_db():
    client = AsyncIOMotorClient(settings.MONGO_URI)
    return client, client[settings.MONGO_DB_NAME]


@celery_app.task(
    name="tasks_scoring.generate_prediction_for_case", bind=False, max_retries=3, default_retry_delay=30
)
def generate_prediction_for_case(failed_payment_id: str) -> None:
    asyncio.run(_generate_prediction_async(failed_payment_id))


async def _generate_prediction_async(failed_payment_id: str) -> None:
    client, db = _get_worker_db()
    try:
        from app.db.repositories import failed_payments_repo, recovery_actions_repo
        from app.models.recovery_action import RecoveryActionCreate, TriggeredBy
        from app.services import recovery_prediction_service

        failed_payment = await failed_payments_repo.get_by_id_unscoped(db, failed_payment_id)
        if failed_payment is None or failed_payment.is_closed():
            logger.info("Skipping scoring for missing/closed case id=%s", failed_payment_id)
            return

        prediction = await recovery_prediction_service.generate_recovery_score(
            db, failed_payment, force_recompute=True
        )

        if prediction.recommended_action:
            await recovery_actions_repo.create_recovery_action(
                db,
                RecoveryActionCreate(
                    business_id=failed_payment.business_id,
                    failed_payment_id=failed_payment.id,
                    recovery_prediction_id=prediction.id,
                    action_type=prediction.recommended_action.channel,
                    sequence_step=prediction.recommended_action.cadence_step,
                    scheduled_at=prediction.recommended_action.next_attempt_at,
                    triggered_by=TriggeredBy.AUTO_ENGINE,
                ),
            )
            logger.info(
                "Auto-scheduled first recovery action for case=%s at %s",
                failed_payment_id,
                prediction.recommended_action.next_attempt_at,
            )
    except Exception:
        logger.exception("generate_prediction_for_case failed for id=%s", failed_payment_id)
        raise
    finally:
        client.close()
