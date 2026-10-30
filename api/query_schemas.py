import uuid
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from api.metric_schemas import NAME_PATTERN, MetricOut, metric_out


class QueryRequest(BaseModel):
    metric: str = Field(pattern=NAME_PATTERN)
    group_by: str | None = Field(default=None, max_length=100)
    time_grain: Literal["day", "week", "month", "quarter", "year"] | None = None
    date_column: str | None = Field(default=None, max_length=100)
    date_from: date | None = None
    date_to: date | None = None  # inclusive
    order: Literal["value_desc", "value_asc", "group_asc", "group_desc"] | None = None
    limit: int = Field(default=100, ge=1, le=1000)

    @field_validator("metric", mode="before")
    @classmethod
    def normalise_metric(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("group_by", "date_column", mode="before")
    @classmethod
    def blank_is_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class QueryResponse(BaseModel):
    query_id: uuid.UUID | None = None
    metric: MetricOut
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    warnings: list[str]


def query_response(outcome) -> QueryResponse:
    return QueryResponse(
        query_id=outcome.query_id,
        metric=metric_out(outcome.metric),
        sql=outcome.display_sql,
        columns=outcome.columns,
        rows=outcome.rows,
        row_count=outcome.row_count,
        truncated=outcome.truncated,
        warnings=outcome.warnings,
    )