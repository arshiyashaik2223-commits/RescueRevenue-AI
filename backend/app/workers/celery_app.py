"""
app/workers/celery_app.py
Celery application bootstrap — broker/backend config and task discovery.

Run the worker with:
    celery -A app.workers.celery_app worker --loglevel=info
Run the beat scheduler (for tasks_scheduler.py sweeps, optional/non-MVP) with:
    celery -A app.workers.celery_app beat --loglevel=info
"""
from celery import Celery

from app.config import settings

celery_app = Celery(
    "revenue_rescue_ai",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.workers.tasks_ingestion",
        "app.workers.tasks_scoring",
        "app.workers.tasks_notifications",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
