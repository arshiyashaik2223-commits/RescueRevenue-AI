"""
app/workers/tasks_notifications.py
Celery task: executes a scheduled/triggered RecoveryAction — for a
payment_retry action, calls Razorpay; for email/sms/whatsapp, generates
AI copy and dispatches it. Updates the RecoveryActions record with the
outcome either way.
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
    name="tasks_notifications.execute_recovery_action", bind=False, max_retries=3, default_retry_delay=60
)
def execute_recovery_action(recovery_action_id: str, notify_customer: bool = True) -> None:
    asyncio.run(_execute_recovery_action_async(recovery_action_id, notify_customer))


async def _execute_recovery_action_async(recovery_action_id: str, notify_customer: bool) -> None:
    client, db = _get_worker_db()
    try:
        from app.db.repositories import failed_payments_repo, recovery_actions_repo
        from app.models.recovery_action import ActionStatus

        action = await recovery_actions_repo.get_by_id_unscoped(db, recovery_action_id)
        if action is None:
            logger.warning("execute_recovery_action: action not found id=%s", recovery_action_id)
            return

        failed_payment = await failed_payments_repo.get_by_id_unscoped(db, str(action.failed_payment_id))
        if failed_payment is None or failed_payment.is_closed():
            await recovery_actions_repo.update_execution(db, action.id, ActionStatus.SKIPPED)
            return

        if action.action_type.value == "payment_retry":
            await _execute_payment_retry(db, action, failed_payment)
        else:
            await _execute_message_send(db, action, failed_payment, notify_customer)
    except Exception:
        logger.exception("execute_recovery_action failed for id=%s", recovery_action_id)
        raise
    finally:
        client.close()


async def _execute_payment_retry(db, action, failed_payment) -> None:
    from app.db.repositories import businesses_repo, failed_payments_repo, recovery_actions_repo, transactions_repo
    from app.models.recovery_action import ActionStatus
    from app.services import razorpay_client

    business = await businesses_repo.get_by_id(db, failed_payment.business_id)
    key_id = (business or {}).get("razorpay_key_id")
    key_secret = (business or {}).get("razorpay_key_secret")

    if not key_id or not key_secret:
        logger.warning("No Razorpay credentials configured for business_id=%s", failed_payment.business_id)
        await recovery_actions_repo.update_execution(db, action.id, ActionStatus.FAILED)
        return

    transaction = await transactions_repo.get_by_id(
        db, failed_payment.business_id, str(failed_payment.transaction_id)
    )
    if transaction is None:
        await recovery_actions_repo.update_execution(db, action.id, ActionStatus.FAILED)
        return

    try:
        await razorpay_client.retry_payment(key_id, key_secret, transaction.razorpay_order_id)
        await failed_payments_repo.increment_retry_count(db, failed_payment.id)
        await recovery_actions_repo.update_execution(db, action.id, ActionStatus.SENT)
    except razorpay_client.RazorpayClientError:
        await recovery_actions_repo.update_execution(db, action.id, ActionStatus.FAILED)


async def _execute_message_send(db, action, failed_payment, notify_customer: bool) -> None:
    from app.db.repositories import recovery_actions_repo
    from app.models.recovery_action import ActionStatus
    from app.services import message_generation_service, notification_service

    if not notify_customer:
        await recovery_actions_repo.update_execution(db, action.id, ActionStatus.SKIPPED)
        return

    try:
        content = await message_generation_service.generate_recovery_message(
            db, failed_payment, action.action_type.value
        )
        await notification_service.dispatch(
            channel=action.action_type.value,
            to_email=failed_payment.customer.email,
            to_phone=failed_payment.customer.phone,
            subject=content.get("subject"),
            body=content["body"],
        )
        await recovery_actions_repo.update_execution(db, action.id, ActionStatus.SENT, message_content=content)
    except (message_generation_service.MessageGenerationError, notification_service.NotificationError):
        logger.exception("Message send failed for action_id=%s", action.id)
        await recovery_actions_repo.update_execution(db, action.id, ActionStatus.FAILED)
