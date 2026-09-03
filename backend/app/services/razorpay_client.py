"""
app/services/razorpay_client.py

Thin wrapper around the Razorpay Python SDK. This is the ONLY file
allowed to import/call the `razorpay` package directly — routes and
other services always go through the functions here.

Used by:
  - app.api.v1.auth_routes.register()      -> verify_credentials
  - app.api.v1.webhook_routes.razorpay_webhook() -> verify_webhook_signature
  - app.services.recovery_action_service    -> retry_payment (upcoming)
"""

import hashlib
import hmac
import logging

import razorpay
from razorpay.errors import BadRequestError, ServerError

logger = logging.getLogger(__name__)


class RazorpayClientError(Exception):
    """Raised when a Razorpay API call fails for a reason not otherwise typed."""


async def verify_credentials(key_id: str, key_secret: str) -> bool:
    """
    Verifies a business's Razorpay API credentials by making a cheap,
    read-only call (fetching the payments list with a limit of 1).
    Used during registration (RegisterRequest.razorpay_key_id/_secret)
    to fail fast with 502 RAZORPAY_KEY_INVALID rather than silently
    storing bad credentials.
    """
    try:
        client = razorpay.Client(auth=(key_id, key_secret))
        client.payment.all({"count": 1})
        return True
    except (BadRequestError, ServerError, Exception) as exc:  # noqa: BLE001
        logger.warning("Razorpay credential verification failed: %s", exc)
        return False


def verify_webhook_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """
    Verifies the `x-razorpay-signature` header against the raw request
    body using HMAC-SHA256, per Razorpay's webhook signing scheme.

    IMPORTANT: `raw_body` must be the exact bytes as received (see the
    note in webhook_routes.py) — re-serializing parsed JSON will break
    this comparison even for a genuinely valid request.

    Uses hmac.compare_digest for the final comparison to avoid a
    timing-attack side channel (a naive `==` comparison on the hex
    digests would leak how many leading characters matched via
    response-time differences).
    """
    computed = hmac.new(
        key=secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(computed, signature)


async def retry_payment(key_id: str, key_secret: str, razorpay_order_id: str) -> dict:
    """
    Triggers a payment retry against Razorpay for a given order.

    Razorpay doesn't have a single unified "retry" API across all
    payment methods — in practice this is typically implemented by
    creating a fresh payment link/order for the customer to complete,
    or (for UPI/cards with saved tokens) re-attempting via the
    Payments API. This wrapper abstracts that choice so callers
    (recovery_action_service) don't need to know the underlying
    Razorpay mechanics.

    Raises RazorpayClientError on any failure — callers translate this
    into their own domain-specific error (e.g.
    recovery_action_service.RazorpayRetryError).
    """
    try:
        client = razorpay.Client(auth=(key_id, key_secret))
        order = client.order.fetch(razorpay_order_id)
        # Re-issue a fresh payment link for the same amount/currency so the
        # customer has a live, payable link again (the original order may
        # have expired). See Razorpay Payment Links API.
        payment_link = client.payment_link.create(
            {
                "amount": order["amount"],
                "currency": order["currency"],
                "description": f"Retry payment for order {razorpay_order_id}",
                "notes": {"original_order_id": razorpay_order_id, "retry": "true"},
            }
        )
        return payment_link
    except (BadRequestError, ServerError, Exception) as exc:  # noqa: BLE001
        logger.warning("Razorpay retry_payment failed for order=%s: %s", razorpay_order_id, exc)
        raise RazorpayClientError(str(exc)) from exc
