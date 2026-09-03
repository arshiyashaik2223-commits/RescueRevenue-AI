"""
app/api/v1/webhook_routes.py

Razorpay webhook ingress endpoint.

This is the system's primary event source: Razorpay POSTs here whenever
a payment succeeds/fails, an order is created, an invoice is
issued/paid/expired, or a subscription is charged/halted. Per the
architecture doc (Section 4, "Async processing" / Section 9.2), this
handler is intentionally minimal:

  1. Verify the HMAC signature against the business's webhook secret.
  2. Acknowledge with 200 as fast as possible (<200ms target) — Razorpay
     retries aggressively on slow/missing acks, and retried deliveries
     are handled safely downstream via the unique index on
     transactions.razorpay_payment_id (see app/db/database.py), so this
     handler does not need its own separate dedup store.
  3. Enqueue the raw payload to a Celery task for all real processing
     (normalization, FailedPayments creation, scoring, etc.) — never do
     that work inline in the request/response cycle.

Per-business webhook URL: see the note in the response to the user
alongside this file — each business configures
`/api/v1/webhooks/razorpay/{business_id}` as their webhook URL in the
Razorpay dashboard, which is what allows signature verification to know
which secret to check against before the payload can be trusted at all.

Depends on (generated in upcoming files):
  - app.services.razorpay_client : verify_webhook_signature
  - app.db.repositories.businesses_repo : get_webhook_secret
  - app.workers.tasks_ingestion : process_webhook_event (Celery task)
"""

import json
import logging

from fastapi import APIRouter, Header, Request, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.exceptions import AppError
from app.db.database import get_database
from app.db.repositories import businesses_repo
from app.services import razorpay_client
from app.workers import tasks_ingestion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post(
    "/razorpay/{business_id}",
    status_code=status.HTTP_200_OK,
    summary="Razorpay webhook ingress (per-business URL)",
)
async def razorpay_webhook(
    business_id: str,
    request: Request,
    x_razorpay_signature: str | None = Header(default=None),
) -> dict:
    """
    Receives a Razorpay webhook delivery, verifies its signature, and
    enqueues it for async processing.

    IMPORTANT: signature verification must be computed over the exact
    raw request body bytes as received — NOT a re-serialized version of
    the parsed JSON, since key ordering/whitespace differences would
    break the HMAC comparison. `request.body()` is used for this reason,
    and JSON parsing happens only after the signature check passes.

    Error responses:
      - 404 BUSINESS_NOT_FOUND    : business_id does not correspond to a
                                     known business (should not happen in
                                     practice if the webhook URL was
                                     configured correctly; more likely
                                     indicates a stale/misconfigured URL)
      - 401 INVALID_SIGNATURE     : x-razorpay-signature header missing
                                     or does not match the computed HMAC
      - 400 MALFORMED_PAYLOAD     : body is not valid JSON
      - 202-equivalent via 200    : Razorpay only cares about 2xx to stop
                                     retrying; we return 200 with a small
                                     body once the event is durably
                                     enqueued
    """
    raw_body = await request.body()

    webhook_secret = await businesses_repo.get_webhook_secret(
        get_database(), business_id
    )
    if webhook_secret is None:
        # Deliberately 404 rather than 401 here: an unknown business_id in
        # the URL path means the webhook URL itself is wrong/stale, which
        # is a configuration problem distinct from "signature didn't match."
        raise AppError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="BUSINESS_NOT_FOUND",
            message="No business found for this webhook URL.",
        )

    if not x_razorpay_signature or not razorpay_client.verify_webhook_signature(
        raw_body, x_razorpay_signature, webhook_secret
    ):
        logger.warning(
            "Razorpay webhook signature verification failed for business_id=%s",
            business_id,
        )
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_SIGNATURE",
            message="Webhook signature verification failed.",
        )

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise AppError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="MALFORMED_PAYLOAD",
            message="Webhook body is not valid JSON.",
        ) from exc

    event_type = payload.get("event", "unknown")

    # Enqueue and return immediately — all normalization, persistence, and
    # downstream scoring/notification triggering happens in the worker
    # (app/workers/tasks_ingestion.py -> app/services/event_ingestion_service.py).
    tasks_ingestion.process_webhook_event.delay(business_id=business_id, payload=payload)

    logger.info(
        "Razorpay webhook accepted: business_id=%s event=%s",
        business_id,
        event_type,
    )

    return {"status": "received"}
