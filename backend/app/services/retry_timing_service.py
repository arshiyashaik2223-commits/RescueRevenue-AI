"""
app/services/retry_timing_service.py
Smart retry timing engine — decides channel, next attempt time, and
cadence step for a recovery action, given a failed payment and its
current recovery_score. Kept separate from scoring per the architecture
doc's module boundaries.
"""
import logging
from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.repositories import recovery_actions_repo
from app.models.failed_payment import FailedPaymentModel

logger = logging.getLogger(__name__)

# Cadence delays by step (v1: fixed schedule, not yet business-hours-aware
# beyond a simple daytime clamp — see _clamp_to_business_hours).
_CADENCE_DELAYS_HOURS = {1: 2, 2: 24, 3: 72}
_DEFAULT_DELAY_HOURS = 96  # steps beyond the defined cadence


async def recommend_next_action(
    db: AsyncIOMotorDatabase,
    failed_payment: FailedPaymentModel,
    recovery_score: float,
) -> dict:
    existing_actions_count = await recovery_actions_repo.count_for_failed_payment(db, failed_payment.id)
    cadence_step = existing_actions_count + 1

    delay_hours = _CADENCE_DELAYS_HOURS.get(cadence_step, _DEFAULT_DELAY_HOURS)
    next_attempt_at = datetime.now(timezone.utc) + timedelta(hours=delay_hours)
    next_attempt_at = _clamp_to_business_hours(next_attempt_at)

    channel = _choose_channel(recovery_score, cadence_step)

    return {"channel": channel, "next_attempt_at": next_attempt_at, "cadence_step": cadence_step}


def _choose_channel(recovery_score: float, cadence_step: int) -> str:
    """
    v1 heuristic: high-confidence cases get a direct payment retry
    first; everything else starts with email (cheapest channel), then
    escalates to SMS on the second touch if still unresolved.
    """
    if recovery_score >= 0.7 and cadence_step == 1:
        return "payment_retry"
    if cadence_step >= 2:
        return "sms"
    return "email"


def _clamp_to_business_hours(when: datetime) -> datetime:
    """
    Pushes a timestamp that would land between 9pm-8am UTC to 9am UTC
    the same/next day. A real implementation would use the customer's
    own timezone (captured on FailedPaymentModel.customer.timezone) —
    flagged here as a v1 simplification using a fixed UTC business-hours
    window rather than per-customer localization.
    """
    if 8 <= when.hour < 21:
        return when
    if when.hour >= 21:
        return when.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return when.replace(hour=9, minute=0, second=0, microsecond=0)
