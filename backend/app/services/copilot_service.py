
"""
RevenueRescue AI Copilot powered by Groq.
Uses curated, read-only analytics tools instead of direct database access.
"""

import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone

from groq import AsyncGroq
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import settings
from app.db.repositories import ai_insights_repo
from app.models.ai_insight import AIInsightCreate, AIInsightModel
from app.services import analytics_service

logger = logging.getLogger(__name__)

_client = AsyncGroq(api_key=settings.GROQ_API_KEY)

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_revenue_summary",
            "description": (
                "Get revenue at risk, revenue recovered, recovery rate "
                "and average recovery time for a date range."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Number of days back from today."
                    }
                },
                "required": ["days"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recovery_metrics",
            "description": (
                "Get the recovery funnel and optional breakdown by "
                "risk_tier, channel or source_type."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer"},
                    "group_by": {
                        "type": "string",
                        "enum": ["risk_tier", "channel", "source_type"],
                    },
                },
                "required": ["days"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_failure_trends",
            "description": (
                "Get a time-series breakdown of payment failure reasons."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer"},
                    "interval": {
                        "type": "string",
                        "enum": ["day", "week", "month"],
                    },
                },
                "required": ["days"],
            },
        },
    },
]

_CACHE_WINDOW = timedelta(hours=1)


async def ask_question(
    db: AsyncIOMotorDatabase,
    business_id,
    user_id,
    question: str,
) -> tuple[AIInsightModel, dict | None]:

    if not settings.GROQ_API_KEY:
        raise RuntimeError(
            "Groq API key is missing. Configure GROQ_API_KEY in backend/.env."
        )

    question_hash = hashlib.sha256(
        question.strip().lower().encode("utf-8")
    ).hexdigest()

    # Check cached answer.
    cached = await ai_insights_repo.get_cached_answer(
        db, business_id, question_hash
    )

    if cached and _is_fresh(cached.created_at):
        logger.info("Copilot returned a cached answer.")
        return cached, None

    tool_calls_made = []
    messages = [{"role": "user", "content": question}]

    system_prompt = (
        "You are RevenueRescue AI's Copilot. Help businesses understand "
        "their payment recovery performance. "
        "Use the provided analytics tools to retrieve actual business data "
        "before answering questions about business performance. "
        "Never invent numbers or assume missing data. "
        "After receiving tool results, explain what they mean. "
        "Keep answers concise, clear and business-friendly, using 2-4 "
        "sentences. If data is unavailable, say so clearly. "
        "Do not claim that payments were automatically recovered or retried "
        "unless the analytics data explicitly supports that claim. "
        "If the data naturally supports a simple bar chart, add a final line "
        'in this exact format: CHART_DATA: '
        '{"type": "bar", "labels": [...], "series": [...]}'
    )

    final_text = ""
    collected_tool_results = []

    # First request: allow Groq to select analytics tools.
    # Second request: force Groq to produce a final answer.
    for request_number in range(2):

        tool_choice = "auto" if request_number == 0 else "none"

        logger.info(
            "Copilot Groq request %s; tool_choice=%s",
            request_number + 1,
            tool_choice,
        )

        response = await _client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                *messages,
            ],
            tools=_TOOLS,
            tool_choice=tool_choice,
            max_completion_tokens=1200,
            temperature=0.2,
        )

        if not response.choices:
            logger.error("Groq returned no response choices.")
            break

        choice = response.choices[0]
        assistant_message = choice.message
        tool_calls = assistant_message.tool_calls or []

        logger.info(
            "Copilot response finish_reason=%s, tool_calls=%s",
            choice.finish_reason,
            len(tool_calls),
        )

        # First response may contain analytics tool calls.
        if tool_calls and request_number == 0:

            # Preserve the assistant's original tool-call message.
            messages.append(
                assistant_message.model_dump(exclude_none=True)
            )

            for tool_call in tool_calls:

                tool_name = tool_call.function.name

                try:
                    tool_input = json.loads(
                        tool_call.function.arguments or "{}"
                    )

                    if not isinstance(tool_input, dict):
                        raise ValueError(
                            "Tool arguments must be a JSON object."
                        )

                    logger.info(
                        "Executing Copilot tool: %s with arguments: %s",
                        tool_name,
                        tool_input,
                    )

                    result = await _execute_tool(
                        db,
                        business_id,
                        tool_name,
                        tool_input,
                    )

                    tool_calls_made.append({
                        "tool": tool_name,
                        "args": tool_input,
                    })

                    collected_tool_results.append({
                        "tool": tool_name,
                        "result": result,
                    })

                except Exception:
                    logger.exception(
                        "Copilot tool execution failed: %s",
                        tool_name,
                    )

                    result = {
                        "error": (
                            f"Unable to execute analytics tool: {tool_name}"
                        )
                    }

                    collected_tool_results.append({
                        "tool": tool_name,
                        "result": result,
                    })

                # Return the tool result to Groq.
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, default=str),
                })

            # Continue to the second request, where tools are disabled.
            continue

        # No tool calls: this is the final response.
        final_text = assistant_message.content or ""
        break

    if not final_text.strip():
        logger.warning(
            "Copilot received no final text. Tool calls completed: %s",
            len(tool_calls_made),
        )

        if collected_tool_results:
            final_text = (
                "I retrieved the requested analytics, but the AI service "
                "did not return a complete explanation. Please try again."
            )
        else:
            final_text = (
                "I couldn't retrieve a complete answer from the AI service. "
                "Please try again."
            )

    answer, chart_data = _extract_chart_data(final_text)

    if not answer:
        answer = (
            "I couldn't generate a complete answer. "
            "Please try asking your question again."
        )

    # Save the answer in MongoDB.
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
            model_used=settings.GROQ_MODEL,
            ttl_at=datetime.now(timezone.utc) + timedelta(days=30),
        ),
    )

    return insight, chart_data


async def _execute_tool(
    db: AsyncIOMotorDatabase,
    business_id,
    tool_name: str,
    tool_input: dict,
) -> dict:

    to_date = date.today()
    days = max(1, min(int(tool_input.get("days", 30)), 365))
    from_date = to_date - timedelta(days=days)

    if tool_name == "get_revenue_summary":

        result = await analytics_service.get_revenue_summary(
            db, business_id, from_date, to_date
        )

        return {
            "revenue_at_risk": result.revenue_at_risk,
            "revenue_recovered": result.revenue_recovered,
            "recovery_rate": result.recovery_rate,
            "avg_time_to_recovery_hours": (
                result.avg_time_to_recovery_hours
            ),
            "currency": result.currency,
        }

    if tool_name == "get_recovery_metrics":

        group_by = tool_input.get("group_by")

        result = await analytics_service.get_recovery_metrics(
            db,
            business_id,
            from_date,
            to_date,
            group_by,
        )

        return {
            "funnel": result.funnel,
            "breakdown": result.breakdown,
        }

    if tool_name == "get_failure_trends":

        interval = tool_input.get("interval", "day")

        result = await analytics_service.get_failure_trends(
            db,
            business_id,
            from_date,
            to_date,
            interval,
        )

        return {
            "series": result.series,
        }

    return {
        "error": f"Unknown tool: {tool_name}"
    }


def _extract_chart_data(text: str) -> tuple[str, dict | None]:

    marker = "CHART_DATA:"

    if marker not in text:
        return text.strip(), None

    answer_part, _, chart_part = text.partition(marker)

    try:
        chart = json.loads(chart_part.strip())

        if not isinstance(chart, dict):
            raise ValueError("Chart data must be a JSON object.")

    except (json.JSONDecodeError, ValueError):
        logger.warning("Copilot returned invalid chart JSON.")
        chart = None

    return answer_part.strip(), chart


def _is_fresh(created_at: datetime) -> bool:

    now = datetime.now(timezone.utc)

    created_at_aware = (
        created_at
        if created_at.tzinfo
        else created_at.replace(tzinfo=timezone.utc)
    )

    return (now - created_at_aware) < _CACHE_WINDOW
