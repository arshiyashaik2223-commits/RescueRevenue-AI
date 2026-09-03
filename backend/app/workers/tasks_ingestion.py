"""
app/workers/tasks_ingestion.py
Celery task: processes a raw Razorpay webhook payload asynchronously,
off the hot request path in app.api.v1.webhook_routes.

Celery tasks are synchronous entrypoints by default; each task creates
its OWN Motor client scoped to a fresh asyncio event loop rather than
reusing the FastAPI process's global connection (app.db.database) —
Celery workers run in a separate process, so the FastAPI app's
connection pool/event loop is not available here.
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
    name="tasks_ingestion.process_webhook_event", bind=False, max_retries=3, default_retry_delay=30
)
def process_webhook_event(business_id: str, payload: dict) -> None:
    asyncio.run(_process_webhook_event_async(business_id, payload))


async def _process_webhook_event_async(business_id: str, payload: dict) -> None:
    client, db = _get_worker_db()
    try:
        from app.services import event_ingestion_service

        failed_payment_id = await event_ingestion_service.ingest_razorpay_event(db, business_id, payload)

        if failed_payment_id:
            from app.workers.tasks_scoring import generate_prediction_for_case

            generate_prediction_for_case.delay(failed_payment_id=failed_payment_id)
    except Exception:
        logger.exception("process_webhook_event failed for business_id=%s", business_id)
        raise
    finally:
        client.close()
