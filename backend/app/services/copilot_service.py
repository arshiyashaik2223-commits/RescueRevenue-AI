"""
app/services/copilot_service.py
AI Copilot — natural-language Q&A over the business's own recovery
data, grounded via Claude tool-use against curated read-only analytics
functions (never raw DB access), per the architecture doc's Section 5.9.
"""
import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone

from anthropic import AsyncAnthropic
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import settings
from app.db.repositories import ai_insights_repo
from app.models.ai_insight import AIInsightCreate, AIInsightModel
from app.services import analytics_service

logger = logging.getLogger(__name__)

_client = AsyncAnthropic(
    api_key=settings.ANTHROPIC_API_KEY,
    default_headers={
        "anthropic-workspace-id": settings.ANTHROPIC_WORKSPACE_ID
    },
)
_TOOLS = [
    {
        "name": "get_revenue_summary",
        "description": "Get top-line revenue-at-risk, revenue-recovered, and recovery-rate KPIs for a date range.",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "Number of days back from today to include."}},
            "required": ["days"],
        },
    },
    {
        "name": "get_recovery_metrics",
        "description": (
            "Get the recovery funnel (detected/attempted/recovered/lost) and an optional "
            "breakdown by risk_tier, channel, or source_type."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer"},
                "group_by": {"type": "string", "enum": ["risk_tier", "channel", "source_type"]},
            },
            "required": ["days"],
        },
    },
    {
        "name": "get_failure_trends",
        "description": "Get a time-series breakdown of failure reasons over a date range.",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer"}, "interval": {"type": "string", "enum": ["day", "week", "month"]}},
            "required": ["days"],
        },
    },
]

_MAX_TOOL_ITERATIONS = 4
_CACHE_WINDOW = timedelta(hours=1)


async def ask_question(
    db: AsyncIOMotorDatabase, business_id, user_id, question: str
) -> tuple[AIInsightModel, dict | None]:
    question_hash = hashlib.sha256(question.strip().lower().encode("utf-8")).hexdigest()

    cached = await ai_insights_repo.get_cached_answer(db, business_id, question_hash)
    if cached and _is_fresh(cached.created_at):
        return cached, None

    tool_calls_made: list[dict] = []

    messages = [{"role": "user", "content": question}]
    system_prompt = (
        "You are RevenueRescue AI's Copilot, helping a business understand their "
        "payment recovery performance. Use the provided tools to fetch real data "
        "before answering — never guess numbers. Keep answers concise (2-4 sentences). "
        "If the data naturally supports a simple bar chart, also return a JSON object "
        'on a final line: CHART_DATA: {"type": "bar", "labels": [...], "series": [...]}'
    )

    final_text = ""
    for _ in range(_MAX_TOOL_ITERATIONS):
        response = await _client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=800,
            system=system_prompt,
            tools=_TOOLS,
            messages=messages,
        )

        tool_use_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
        text_blocks = [b.text for b in response.content if getattr(b, "type", None) == "text"]
        final_text = "\n".join(text_blocks)

        if not tool_use_blocks:
            break

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in tool_use_blocks:
            result = await _execute_tool(db, business_id, block.name, block.input)
            tool_calls_made.append({"tool": block.name, "args": block.input})
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result, default=str)}
            )
        messages.append({"role": "user", "content": tool_results})

    answer, chart_data = _extract_chart_data(final_text)

    insight = await ai_insights_repo.create_insight(
        db,
        AIInsightCreate(
            business_id=business_id,
            user_id=user_id,
            question=question,
            question_hash=question_hash,
            answer=answer,
            tool_calls_made=tool_calls_made,
            data_snapshot_ref={},
            model_used=settings.ANTHROPIC_MODEL,
            ttl_at=datetime.now(timezone.utc) + timedelta(days=30),
        ),
    )

    return insight, chart_data


async def _execute_tool(db: AsyncIOMotorDatabase, business_id, tool_name: str, tool_input: dict) -> dict:
    to_date = date.today()
    days = tool_input.get("days", 30)
    from_date = to_date - timedelta(days=days)

    if tool_name == "get_revenue_summary":
        result = await analytics_service.get_revenue_summary(db, business_id, from_date, to_date)
        return {
            "revenue_at_risk": result.revenue_at_risk,
            "revenue_recovered": result.revenue_recovered,
            "recovery_rate": result.recovery_rate,
            "avg_time_to_recovery_hours": result.avg_time_to_recovery_hours,
            "currency": result.currency,
        }
    if tool_name == "get_recovery_metrics":
        result = await analytics_service.get_recovery_metrics(
            db, business_id, from_date, to_date, tool_input.get("group_by")
        )
        return {"funnel": result.funnel, "breakdown": result.breakdown}
    if tool_name == "get_failure_trends":
        result = await analytics_service.get_failure_trends(
            db, business_id, from_date, to_date, tool_input.get("interval", "day")
        )
        return {"series": result.series}
    return {"error": f"Unknown tool: {tool_name}"}


def _extract_chart_data(text: str) -> tuple[str, dict | None]:
    marker = "CHART_DATA:"
    if marker not in text:
        return text.strip(), None
    answer_part, _, chart_part = text.partition(marker)
    try:
        chart = json.loads(chart_part.strip())
    except json.JSONDecodeError:
        chart = None
    return answer_part.strip(), chart


def _is_fresh(created_at: datetime) -> bool:
    now = datetime.now(timezone.utc)
    created_at_aware = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
    return (now - created_at_aware) < _CACHE_WINDOW
