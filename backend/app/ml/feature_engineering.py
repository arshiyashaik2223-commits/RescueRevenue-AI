"""
app/ml/feature_engineering.py
Builds the feature vector consumed by app.ml.model_infer.predict().
v1 heuristic feature set per the architecture doc's scoring_service
description — pulls a small amount of customer history from the
Transactions collection to compute a success-ratio feature.
"""
import logging
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.failed_payment import FailedPaymentModel

logger = logging.getLogger(__name__)


async def build_features(db: AsyncIOMotorDatabase, failed_payment: FailedPaymentModel) -> dict:
    customer_id = failed_payment.customer.customer_id

    total = await db["transactions"].count_documents(
        {"business_id": failed_payment.business_id, "customer.customer_id": customer_id, "type": "payment"}
    )
    successful = await db["transactions"].count_documents(
        {
            "business_id": failed_payment.business_id,
            "customer.customer_id": customer_id,
            "type": "payment",
            "status": "success",
        }
    )
    past_success_ratio = round(successful / total, 4) if total > 0 else 0.5  # neutral prior for new customers

    now = datetime.now(timezone.utc)
    detected_at = failed_payment.detected_at
    detected_at_aware = detected_at if detected_at.tzinfo else detected_at.replace(tzinfo=timezone.utc)
    hours_since_failure = round((now - detected_at_aware).total_seconds() / 3600, 2)

    avg_amount_docs = await db["transactions"].aggregate(
        [
            {
                "$match": {
                    "business_id": failed_payment.business_id,
                    "customer.customer_id": customer_id,
                    "status": "success",
                }
            },
            {"$group": {"_id": None, "avg_amount": {"$avg": "$amount"}}},
        ]
    ).to_list(length=1)
    avg_amount = avg_amount_docs[0]["avg_amount"] if avg_amount_docs else failed_payment.amount
    amount_relative_to_avg = round(failed_payment.amount / avg_amount, 4) if avg_amount else 1.0

    return {
        "failure_reason_category": failed_payment.failure_reason_category.value,
        "amount_relative_to_avg": amount_relative_to_avg,
        "customer_past_success_ratio": past_success_ratio,
        "hours_since_failure": hours_since_failure,
        "day_of_week": detected_at_aware.strftime("%A"),
        "prior_retry_count": failed_payment.retry_attempts_count,
    }
