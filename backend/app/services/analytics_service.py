"""
app/services/analytics_service.py
Pandas-based aggregation logic backing Section F (Analytics) endpoints,
and reused as the AI Copilot's tool-use data backend (copilot_service.py).

v1 implementation: pulls the relevant window of FailedPayments documents
into memory via Motor, loads into a pandas DataFrame, and computes
aggregates there. Fine at hackathon/MVP data volumes; a production-scale
version would push more of this into MongoDB aggregation pipelines to
avoid pulling full documents into app memory.
"""
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone

import pandas as pd
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)


@dataclass
class RevenueSummary:
    revenue_at_risk: int
    revenue_recovered: int
    recovery_rate: float
    avg_time_to_recovery_hours: float
    currency: str


@dataclass
class RecoveryMetrics:
    funnel: dict
    breakdown: dict | None = None


@dataclass
class FailureTrends:
    series: list = field(default_factory=list)


def _range(from_date: date, to_date: date) -> dict:
    return {
        "$gte": datetime.combine(from_date, time.min, tzinfo=timezone.utc),
        "$lte": datetime.combine(to_date, time.max, tzinfo=timezone.utc),
    }


async def _fetch_failed_payments_df(db: AsyncIOMotorDatabase, business_id, from_date: date, to_date: date) -> pd.DataFrame:
    cursor = db["failed_payments"].find(
        {"business_id": business_id, "detected_at": _range(from_date, to_date)}
    )
    docs = [doc async for doc in cursor]
    if not docs:
        return pd.DataFrame(
            columns=[
                "amount", "currency", "status", "failure_reason_category",
                "retry_attempts_count", "recovered_amount", "detected_at", "recovered_at",
            ]
        )
    return pd.DataFrame(docs)


async def get_revenue_summary(
    db: AsyncIOMotorDatabase, business_id, from_date: date, to_date: date, currency: str | None = None
) -> RevenueSummary:
    df = await _fetch_failed_payments_df(db, business_id, from_date, to_date)
    if currency and not df.empty:
        df = df[df["currency"] == currency]

    resolved_currency = currency or (df["currency"].iloc[0] if not df.empty else "INR")

    revenue_at_risk = int(df["amount"].sum()) if not df.empty else 0
    recovered_df = df[df["status"] == "recovered"] if not df.empty else df
    revenue_recovered = int(recovered_df["recovered_amount"].fillna(0).sum()) if not recovered_df.empty else 0
    recovery_rate = round(revenue_recovered / revenue_at_risk, 4) if revenue_at_risk > 0 else 0.0

    avg_hours = 0.0
    if not recovered_df.empty:
        recovered_with_times = recovered_df.dropna(subset=["recovered_at", "detected_at"])
        if not recovered_with_times.empty:
            deltas = pd.to_datetime(recovered_with_times["recovered_at"]) - pd.to_datetime(
                recovered_with_times["detected_at"]
            )
            avg_hours = round(deltas.dt.total_seconds().mean() / 3600, 2)

    return RevenueSummary(
        revenue_at_risk=revenue_at_risk,
        revenue_recovered=revenue_recovered,
        recovery_rate=recovery_rate,
        avg_time_to_recovery_hours=avg_hours,
        currency=resolved_currency,
    )


async def get_recovery_metrics(
    db: AsyncIOMotorDatabase, business_id, from_date: date, to_date: date, group_by: str | None = None
) -> RecoveryMetrics:
    df = await _fetch_failed_payments_df(db, business_id, from_date, to_date)

    detected = len(df)
    recovered = int((df["status"] == "recovered").sum()) if not df.empty else 0
    lost = int(df["status"].isin(["lost", "expired"]).sum()) if not df.empty else 0
    attempted = (
        int(((df["status"] != "open") | (df["retry_attempts_count"] > 0)).sum()) if not df.empty else 0
    )

    funnel = {"detected": detected, "attempted": attempted, "recovered": recovered, "lost": lost}

    breakdown = None
    if group_by == "source_type" and not df.empty and "source_type" in df.columns:
        grouped = df.groupby("source_type").apply(
            lambda g: {"detected": len(g), "recovered": int((g["status"] == "recovered").sum())}
        )
        breakdown = {"group_by": group_by, "data": [{"key": k, **v} for k, v in grouped.items()]}
    elif group_by == "risk_tier":
        breakdown = await _risk_tier_breakdown(db, business_id, from_date, to_date)
    elif group_by == "channel":
        breakdown = await _channel_breakdown(db, business_id, from_date, to_date)

    return RecoveryMetrics(funnel=funnel, breakdown=breakdown)


async def _risk_tier_breakdown(db: AsyncIOMotorDatabase, business_id, from_date: date, to_date: date) -> dict:
    pipeline = [
        {"$match": {"business_id": business_id, "detected_at": _range(from_date, to_date)}},
        {
            "$lookup": {
                "from": "recovery_predictions",
                "let": {"fp_id": "$_id"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$failed_payment_id", "$$fp_id"]},
                                    {"$eq": ["$is_current", True]},
                                ]
                            }
                        }
                    },
                    {"$limit": 1},
                ],
                "as": "prediction",
            }
        },
        {"$addFields": {"risk_tier": {"$arrayElemAt": ["$prediction.risk_tier", 0]}}},
        {"$match": {"risk_tier": {"$ne": None}}},
        {
            "$group": {
                "_id": "$risk_tier",
                "detected": {"$sum": 1},
                "recovered": {"$sum": {"$cond": [{"$eq": ["$status", "recovered"]}, 1, 0]}},
            }
        },
    ]
    data = []
    async for doc in db["failed_payments"].aggregate(pipeline):
        data.append({"key": doc["_id"], "detected": doc["detected"], "recovered": doc["recovered"]})
    return {"group_by": "risk_tier", "data": data}


async def _channel_breakdown(db: AsyncIOMotorDatabase, business_id, from_date: date, to_date: date) -> dict:
    pipeline = [
        {"$match": {"business_id": business_id, "created_at": _range(from_date, to_date)}},
        {
            "$group": {
                "_id": "$action_type",
                "detected": {"$sum": 1},
                "recovered": {"$sum": {"$cond": [{"$eq": ["$outcome", "payment_succeeded"]}, 1, 0]}},
            }
        },
    ]
    data = []
    async for doc in db["recovery_actions"].aggregate(pipeline):
        data.append({"key": doc["_id"], "detected": doc["detected"], "recovered": doc["recovered"]})
    return {"group_by": "channel", "data": data}


async def get_failure_trends(
    db: AsyncIOMotorDatabase,
    business_id,
    from_date: date,
    to_date: date,
    interval: str = "day",
    failure_reason_category: str | None = None,
) -> FailureTrends:
    df = await _fetch_failed_payments_df(db, business_id, from_date, to_date)
    if failure_reason_category and not df.empty:
        df = df[df["failure_reason_category"] == failure_reason_category]

    if df.empty:
        return FailureTrends(series=[])

    df["detected_at"] = pd.to_datetime(df["detected_at"])
    freq_map = {"day": "D", "week": "W-MON", "month": "MS"}
    freq = freq_map.get(interval, "D")

    series = []
    for bucket_start, group in df.set_index("detected_at").groupby(pd.Grouper(freq=freq)):
        if group.empty:
            continue
        by_reason = group["failure_reason_category"].value_counts().to_dict()
        series.append(
            {
                "bucket_start": bucket_start.date().isoformat(),
                "total_failures": int(len(group)),
                "by_reason": {str(k): int(v) for k, v in by_reason.items()},
            }
        )
    return FailureTrends(series=series)
