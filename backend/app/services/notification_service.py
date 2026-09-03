"""
app/services/notification_service.py
Multi-channel dispatch — sends the AI-generated recovery message via
email/SMS/WhatsApp. v1: logs the send and returns success in "dev mode"
when no provider key is configured; wire in a real provider SDK
(SendGrid/Twilio/etc., per .env.example) before production use. Kept
provider-agnostic behind this module so swapping providers never
touches calling code.
"""
import logging

from app.config import settings

logger = logging.getLogger(__name__)


class NotificationError(Exception):
    """Raised when a message fails to send via its channel's provider."""


async def send_email(to_email: str, subject: str, body: str) -> bool:
    if not settings.EMAIL_API_KEY:
        logger.info("[DEV MODE] Email not sent (no EMAIL_API_KEY configured). To=%s Subject=%s", to_email, subject)
        return True
    # TODO: wire in real provider SDK (SendGrid/SES/Postmark) here.
    logger.info("Email sent (stub): to=%s subject=%s", to_email, subject)
    return True


async def send_sms(to_number: str, body: str) -> bool:
    if not settings.SMS_AUTH_TOKEN:
        logger.info("[DEV MODE] SMS not sent (no SMS_AUTH_TOKEN configured). To=%s", to_number)
        return True
    # TODO: wire in real provider SDK (Twilio/MSG91) here.
    logger.info("SMS sent (stub): to=%s", to_number)
    return True


async def send_whatsapp(to_number: str, body: str) -> bool:
    if not settings.WHATSAPP_API_KEY:
        logger.info("[DEV MODE] WhatsApp not sent (no WHATSAPP_API_KEY configured). To=%s", to_number)
        return True
    # TODO: wire in real provider SDK (WhatsApp Business API/Twilio) here.
    logger.info("WhatsApp sent (stub): to=%s", to_number)
    return True


async def dispatch(channel: str, to_email: str | None, to_phone: str | None, subject: str | None, body: str) -> bool:
    if channel == "email":
        if not to_email:
            raise NotificationError("Customer has no email on file for an email dispatch.")
        return await send_email(to_email, subject or "", body)
    if channel == "sms":
        if not to_phone:
            raise NotificationError("Customer has no phone on file for an SMS dispatch.")
        return await send_sms(to_phone, body)
    if channel == "whatsapp":
        if not to_phone:
            raise NotificationError("Customer has no phone on file for a WhatsApp dispatch.")
        return await send_whatsapp(to_phone, body)
    raise NotificationError(f"Unknown channel: {channel}")
