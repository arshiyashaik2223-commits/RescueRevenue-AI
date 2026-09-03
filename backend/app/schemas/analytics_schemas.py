"""
app/schemas/analytics_schemas.py
API-facing response schemas for Section F (Analytics).
"""
from pydantic import BaseModel


class Period(BaseModel):
    from_date: str
    to_date: str


class RevenueSummaryResponse(BaseModel):
    period: Period
    revenue_at_risk: int
    revenue_recovered: int
    recovery_rate: float
    avg_time_to_recovery_hours: float
    currency: str


class Funnel(BaseModel):
    detected: int
    attempted: int
    recovered: int
    lost: int


class BreakdownItem(BaseModel):
    key: str
    detected: int
    recovered: int


class Breakdown(BaseModel):
    group_by: str
    data: list[BreakdownItem]


class RecoveryMetricsResponse(BaseModel):
    period: Period
    funnel: Funnel
    breakdown: Breakdown | None = None


class TrendBucket(BaseModel):
    bucket_start: str
    total_failures: int
    by_reason: dict[str, int]


class FailureTrendsResponse(BaseModel):
    period: Period
    interval: str
    series: list[TrendBucket]
