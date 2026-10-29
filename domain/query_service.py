import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from core.logging import log
from domain import dataset_service, metric_service
from domain.metric_service import MetricNotFound
from domain.models import Dataset, QueryLog
from domain.query_builder import QueryRejected, QuerySpec, build_query, quote_ident
from domain.query_executor import QueryExecutionError, execute_readonly
from domain.query_result import ResultInvalid, validate_result


@dataclass(frozen=True)
class QueryOutcome:
    query_id: uuid.UUID | None
    metric: Any
    display_sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    warnings: list[str]


def describe_spec(spec: QuerySpec) -> str:
    parts = [f"metric={spec.metric}"]
    if spec.group_by:
        parts.append(f"group_by={spec.group_by}")
    if spec.time_grain:
        parts.append(f"time_grain={spec.time_grain}")
    if spec.date_column:
        parts.append(f"date_column={spec.date_column}")
    if spec.date_from:
        parts.append(f"date_from={spec.date_from.isoformat()}")
    if spec.date_to:
        parts.append(f"date_to={spec.date_to.isoformat()}")
    if spec.order:
        parts.append(f"order={spec.order}")
    parts.append(f"limit={spec.limit}")
    return ("structured query: " + " ".join(parts))[:500]


def _active_metric(db: Session, dataset_id: uuid.UUID, name: str):
    try:
        return metric_service.get_active(db, dataset_id, name)
    except MetricNotFound:
        names = [metric.name for metric in metric_service.list_active(db, dataset_id)]
        hint = f" Available metrics: {', '.join(names[:30])}." if names else " This dataset has no metrics yet."
        raise QueryRejected(f"Unknown metric '{name[:60]}'.{hint}") from None


def _log_attempt(
    db: Session,
    dataset_id: uuid.UUID,
    user_id: str | None,
    question: str,
    metric: Any,
    built: Any,
    status: str,
    reason: str | None = None,
    row_count: int | None = None,
) -> uuid.UUID | None:
    """Audit row for every attempt. Never allowed to break the request."""
    try:
        entry = QueryLog(
            dataset_id=dataset_id,
            user_id=user_id,
            question=question[:2000],
            matched_metric_id=metric.id if metric is not None else None,
            generated_sql=built.sql if built is not None else None,
            status=status,
            rejection_reason=reason,
            row_count=row_count,
            tokens_used=0,
        )
        db.add(entry)
        db.commit()
        return entry.id
    except Exception:
        db.rollback()
        log.error("query_log_failed", status=status)
        return None


def run_query(
    db: Session,
    dataset: Dataset,
    user_id: str | None,
    spec: QuerySpec,
    question: str | None = None,
) -> QueryOutcome:
    dataset_id = dataset.id
    table_name = dataset.table_name
    is_ready = dataset.status == "ready"
    question_text = question or describe_spec(spec)
    metric = None
    built = None

    try:
        if not is_ready:
            raise QueryRejected("The dataset is not ready yet.")
        metric = _active_metric(db, dataset_id, spec.metric)
        columns = {column.name: column.dtype for column in dataset_service.get_columns(db, dataset_id)}
        built = build_query(spec, metric, table_name, columns)
        column_names, rows = execute_readonly(built.sql, built.limit + 1)
        result = validate_result(column_names, rows, built)
    except QueryRejected as exc:
        _log_attempt(db, dataset_id, user_id, question_text, metric, built, "rejected", reason=str(exc))
        raise
    except (QueryExecutionError, ResultInvalid) as exc:
        _log_attempt(db, dataset_id, user_id, question_text, metric, built, "failed", reason=str(exc))
        raise

    display_sql = built.sql.replace(quote_ident(built.table_name), '"dataset"')
    query_id = _log_attempt(
        db, dataset_id, user_id, question_text, metric, built, "answered", row_count=result.row_count
    )
    return QueryOutcome(
        query_id=query_id,
        metric=metric,
        display_sql=display_sql,
        columns=result.columns,
        rows=result.rows,
        row_count=result.row_count,
        truncated=result.truncated,
        warnings=result.warnings,
    )