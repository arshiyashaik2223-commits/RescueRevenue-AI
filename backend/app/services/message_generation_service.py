"""
app/services/message_generation_service.py
Claude-powered recovery message generation. Builds a prompt from the
business's brand voice config + failed payment context, calls the
Claude API, and returns validated channel-specific copy.
"""
import json
import logging

from anthropic import AsyncAnthropic
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import settings
from app.db.repositories import businesses_repo
from app.models.failed_payment import FailedPaymentModel

logger = logging.getLogger(__name__)

_client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

_MAX_SUBJECT_LENGTH = 100
_MAX_BODY_LENGTH = 1200
# v1: a short hand-curated list of phrases that read as manipulative/
# dark-pattern urgency — extend as needed. Real content moderation would
# use a more systematic check; this is a lightweight guardrail.
_BANNED_PHRASES = ["act now or lose everything", "final final notice", "guaranteed"]


class MessageGenerationError(Exception):
    """Raised when Claude fails to produce usable message content."""


async def generate_recovery_message(
    db: AsyncIOMotorDatabase,
    failed_payment: FailedPaymentModel,
    channel: str,
) -> dict:
    """
    Returns {"channel": ..., "subject": ... | None, "body": ..., "ai_model_used": ...}
    """
    business = await businesses_repo.get_by_id(db, failed_payment.business_id)
    brand_voice = (business or {}).get("brand_voice_config", {}) if business else {}
    tone = brand_voice.get("tone", "helpful and professional")
    signature = brand_voice.get("signature", "The Team")

    prompt = _build_prompt(failed_payment, channel, tone, signature)

    try:
        response = await _client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        parsed = json.loads(raw_text)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Claude message generation failed for failed_payment_id=%s", failed_payment.id)
        raise MessageGenerationError(str(exc)) from exc

    subject = parsed.get("subject") if channel == "email" else None
    body = parsed.get("body", "")

    _validate_content(subject, body)

    return {
        "channel": channel,
        "subject": subject,
        "body": body,
        "ai_model_used": settings.ANTHROPIC_MODEL,
    }


def _build_prompt(failed_payment: FailedPaymentModel, channel: str, tone: str, signature: str) -> str:
    amount_display = f"{failed_payment.amount / 100:.2f} {failed_payment.currency}"
    format_hint = (
        'Respond ONLY with JSON: {"subject": "...", "body": "..."}'
        if channel == "email"
        else 'Respond ONLY with JSON: {"body": "..."} (no subject — this is a short '
        "SMS/WhatsApp message, under 300 characters)"
    )
    return f"""You are writing a payment recovery message on behalf of a business.
Tone: {tone}. Sign off as "{signature}".
Customer name: {failed_payment.customer.name}
Amount due: {amount_display}
Failure reason: {failed_payment.failure_reason_category.value}
Channel: {channel}

Write a helpful, non-pushy message asking the customer to complete their payment.
Do not use false urgency, dark patterns, or guarantees. Include a clear next step.
{format_hint}
"""


def _validate_content(subject: str | None, body: str) -> None:
    if subject and len(subject) > _MAX_SUBJECT_LENGTH:
        raise MessageGenerationError("Generated subject exceeds max length.")
    if len(body) > _MAX_BODY_LENGTH:
        raise MessageGenerationError("Generated body exceeds max length.")
    lowered = f"{subject or ''} {body}".lower()
    for phrase in _BANNED_PHRASES:
        if phrase in lowered:
            raise MessageGenerationError(f"Generated content contains a banned phrase: '{phrase}'.")
