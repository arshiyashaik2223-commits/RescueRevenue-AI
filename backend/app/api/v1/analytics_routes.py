"""
app/api/v1/analytics_routes.py

Analytics endpoints: Revenue Summary, Recovery Metrics, Failure Trends.
Implements Section F of RevenueRescue-AI-API-Specification.md exactly —
URLs, request/response shapes, validation rules, and error codes below
all mirror that document.

All three endpoints are read-only and open to any authenticated role
(admin, analyst, viewer), per the spec's endpoint summary table. Actual
aggregation (Pandas-based, per the approved tech stack) lives in
app/services/analytics_service.py — this router only validates query
params, applies default date windows, and shapes responses.

Depends on (generated in upcoming files):
  - app.schemas.analytics_schemas : RevenueSummaryResponse,
                                     RecoveryMetricsResponse,
                                     FailureTrendsResponse
  - app.services.analytics_service : get_revenue_summary,
                                     get_recovery_metrics,
                                     get_failure_trends
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.exceptions import AppError
from app.core.security import get_current_user
from app.db.database import get_database
from app.models.user import UserModel
from app.schemas.analytics_schemas import (
    FailureTrendsResponse,
    RecoveryMetricsResponse,
    RevenueSummaryResponse,
)
from app.services import analytics_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["Analytics"])

_DEFAULT_WINDOW_DAYS = 30
_MAX_WINDOW_DAYS = 366  # per API spec F.1's explicit "max window 366 days" rule

_VALID_GROUP_BY = ("risk_tier", "channel", "source_type")
_VALID_INTERVALS = ("day", "week", "month")
_VALID_FAILURE_REASONS = (
    "insufficient_funds",
    "card_expired",
    "bank_declined",
    "risk_blocked",
    "timeout",
    "other",
)


def _resolve_period(from_date: date | None, to_date: date | None) -> tuple[date, date]:
    """
    Applies the shared default window (last 30 days) when either bound is
    omitted, matching the "last 30 days" default noted on every analytics
    endpoint in the API spec.
    """
    today = datetime.now(timezone.utc).date()
    resolved_to = to_date or today
    resolved_from = from_date or (resolved_to - timedelta(days=_DEFAULT_WINDOW_DAYS))
    return resolved_from, resolved_to


def _validate_period(from_date: date, to_date: date, enforce_max_window: bool = False) -> None:
    if from_date > to_date:
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message="from_date must not be after to_date.",
            details={"from_date": "Must be <= to_date."},
        )
    if enforce_max_window and (to_date - from_date).days > _MAX_WINDOW_DAYS:
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message=f"Reporting window cannot exceed {_MAX_WINDOW_DAYS} days.",
            details={"to_date": "Window between from_date and to_date is too large."},
        )


def _validate_currency(currency: str | None) -> None:
    if currency is not None and (len(currency) != 3 or not currency.isalpha()):
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message="currency must be a valid 3-letter ISO 4217 code.",
            details={"currency": currency},
        )


# ----------------------------------------------------------------------
# F.1 Revenue Summary
# ----------------------------------------------------------------------
@router.get(
    "/revenue-summary",
    response_model=RevenueSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Top-line revenue-at-risk / recovered / recovery-rate KPIs",
)
async def revenue_summary(
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: UserModel = Depends(get_current_user),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    currency: str | None = Query(default=None),
) -> RevenueSummaryResponse:
    """
    Error responses:
      - 422 VALIDATION_ERROR : invalid date range, window > 366 days,
        or unrecognized currency code
    """
    resolved_from, resolved_to = _resolve_period(from_date, to_date)
    _validate_period(resolved_from, resolved_to, enforce_max_window=True)
    _validate_currency(currency)

    summary = await analytics_service.get_revenue_summary(
        db,
        business_id=current_user.business_id,
        from_date=resolved_from,
        to_date=resolved_to,
        currency=currency,
    )

    return RevenueSummaryResponse(
        period={"from_date": resolved_from.isoformat(), "to_date": resolved_to.isoformat()},
        revenue_at_risk=summary.revenue_at_risk,
        revenue_recovered=summary.revenue_recovered,
        recovery_rate=summary.recovery_rate,
        avg_time_to_recovery_hours=summary.avg_time_to_recovery_hours,
        currency=summary.currency,
    )


# ----------------------------------------------------------------------
# F.2 Recovery Metrics
# ----------------------------------------------------------------------
@router.get(
    "/recovery-metrics",
    response_model=RecoveryMetricsResponse,
    status_code=status.HTTP_200_OK,
    summary="Recovery funnel and optional breakdown by risk_tier/channel/source_type",
)
async def recovery_metrics(
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: UserModel = Depends(get_current_user),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    group_by: Literal["risk_tier", "channel", "source_type"] | None = Query(default=None),
) -> RecoveryMetricsResponse:
    """
    Error responses:
      - 422 VALIDATION_ERROR : invalid group_by value or bad date range
    """
    resolved_from, resolved_to = _resolve_period(from_date, to_date)
    _validate_period(resolved_from, resolved_to)

    if group_by is not None and group_by not in _VALID_GROUP_BY:
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message=f"group_by must be one of: {', '.join(_VALID_GROUP_BY)}.",
            details={"group_by": group_by},
        )

    metrics = await analytics_service.get_recovery_metrics(
        db,
        business_id=current_user.business_id,
        from_date=resolved_from,
        to_date=resolved_to,
        group_by=group_by,
    )

    response = RecoveryMetricsResponse(
        period={"from_date": resolved_from.isoformat(), "to_date": resolved_to.isoformat()},
        funnel=metrics.funnel,
        breakdown=metrics.breakdown if group_by else None,
    )
    return response


# ----------------------------------------------------------------------
# F.3 Failure Trends
# ----------------------------------------------------------------------
@router.get(
    "/failure-trends",
    response_model=FailureTrendsResponse,
    status_code=status.HTTP_200_OK,
    summary="Time-series breakdown of failure reasons",
)
async def failure_trends(
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: UserModel = Depends(get_current_user),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    interval: Literal["day", "week", "month"] = Query(default="day"),
    failure_reason_category: str | None = Query(default=None),
) -> FailureTrendsResponse:
    """
    Error responses:
      - 422 VALIDATION_ERROR : invalid interval value, invalid
        failure_reason_category, or bad date range
    """
    resolved_from, resolved_to = _resolve_period(from_date, to_date)
    _validate_period(resolved_from, resolved_to)

    if interval not in _VALID_INTERVALS:
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message=f"interval must be one of: {', '.join(_VALID_INTERVALS)}.",
            details={"interval": interval},
        )

    if failure_reason_category is not None and failure_reason_category not in _VALID_FAILURE_REASONS:
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message=f"failure_reason_category must be one of: {', '.join(_VALID_FAILURE_REASONS)}.",
            details={"failure_reason_category": failure_reason_category},
        )

    trends = await analytics_service.get_failure_trends(
        db,
        business_id=current_user.business_id,
        from_date=resolved_from,
        to_date=resolved_to,
        interval=interval,
        failure_reason_category=failure_reason_category,
    )

    return FailureTrendsResponse(
        period={"from_date": resolved_from.isoformat(), "to_date": resolved_to.isoformat()},
        interval=interval,
        series=trends.series,
    )
