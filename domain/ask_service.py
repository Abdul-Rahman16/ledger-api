from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from core.llm import complete_json
from core.llm_types import LLMUnavailable
from domain import dataset_service, metric_service, query_service
from domain.models import Dataset
from domain.query_builder import QueryRejected, QuerySpec
from domain.query_service import QueryOutcome
from domain.resolver import (
    MetricInfo,
    QuestionInvalid,
    ResolverContext,
    clean_question,
    resolve_question,
)


@dataclass(frozen=True)
class AskOutcome:
    status: str  # "answered" or "needs_clarification"
    question: str
    clarification: str | None
    spec: QuerySpec | None
    query: QueryOutcome | None
    provider: str | None
    tokens_used: int
    available_metrics: list[str]


def ask_question(
    db: Session,
    dataset: Dataset,
    user_id: str | None,
    question: str,
    *,
    today: date | None = None,
    llm: Callable[[str, str], Any] = complete_json,
) -> AskOutcome:
    dataset_id = dataset.id
    is_ready = dataset.status == "ready"

    try:
        cleaned = clean_question(question)
    except QuestionInvalid as exc:
        query_service.log_attempt(db, dataset_id, user_id, "(invalid question)", None, None,
                                  "rejected", reason=str(exc))
        raise QueryRejected(str(exc)) from None

    if not is_ready:
        query_service.log_attempt(db, dataset_id, user_id, cleaned, None, None,
                                  "rejected", reason="The dataset is not ready yet.")
        raise QueryRejected("The dataset is not ready yet.")

    metrics = metric_service.list_active(db, dataset_id)
    metric_infos = [MetricInfo(name=metric.name, description=metric.description) for metric in metrics]
    names = [info.name for info in metric_infos]

    if not metric_infos:
        message = "This dataset has no metrics yet. Define a metric first, then ask again."
        query_service.log_attempt(db, dataset_id, user_id, cleaned, None, None,
                                  "rejected", reason=f"clarification: {message}")
        return AskOutcome("needs_clarification", cleaned, message, None, None, None, 0, names)

    columns = {column.name: column.dtype for column in dataset_service.get_columns(db, dataset_id)}
    context = ResolverContext(
        metrics=metric_infos,
        columns=columns,
        today=today or datetime.now(timezone.utc).date(),
    )

    try:
        resolution = resolve_question(cleaned, context, llm)
    except LLMUnavailable as exc:
        query_service.log_attempt(db, dataset_id, user_id, cleaned, None, None,
                                  "failed", reason=str(exc))
        raise

    if resolution.clarification:
        query_service.log_attempt(
            db, dataset_id, user_id, cleaned, None, None, "rejected",
            reason=f"clarification: {resolution.clarification}", tokens_used=resolution.tokens,
        )
        return AskOutcome(
            "needs_clarification", cleaned, resolution.clarification, None, None,
            resolution.provider, resolution.tokens, names,
        )

    outcome = query_service.run_query(
        db, dataset, user_id, resolution.spec, question=cleaned, tokens_used=resolution.tokens
    )
    return AskOutcome(
        "answered", cleaned, None, resolution.spec, outcome,
        resolution.provider, resolution.tokens, names,
    )