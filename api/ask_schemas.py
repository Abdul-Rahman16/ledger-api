from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from api.query_schemas import QueryResponse, query_response
from domain.ask_service import AskOutcome


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class InterpretationOut(BaseModel):
    """How the question was understood, so the user can see and verify it."""

    metric: str
    group_by: str | None = None
    time_grain: str | None = None
    date_column: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    order: str | None = None
    limit: int


class AskResponse(BaseModel):
    status: Literal["answered", "needs_clarification"]
    question: str
    clarification: str | None = None
    available_metrics: list[str] = []
    interpretation: InterpretationOut | None = None
    result: QueryResponse | None = None
    provider: str | None = None
    tokens_used: int = 0


def ask_response(outcome: AskOutcome) -> AskResponse:
    interpretation = None
    if outcome.spec is not None:
        spec = outcome.spec
        interpretation = InterpretationOut(
            metric=spec.metric,
            group_by=spec.group_by,
            time_grain=spec.time_grain,
            date_column=spec.date_column,
            date_from=spec.date_from,
            date_to=spec.date_to,
            order=spec.order,
            limit=spec.limit,
        )
    return AskResponse(
        status=outcome.status,
        question=outcome.question,
        clarification=outcome.clarification,
        available_metrics=outcome.available_metrics,
        interpretation=interpretation,
        result=query_response(outcome.query) if outcome.query is not None else None,
        provider=outcome.provider,
        tokens_used=outcome.tokens_used,
    )