import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

NAME_PATTERN = r"^[a-z][a-z0-9_]{1,59}$"


class MetricIn(BaseModel):
    expression: str = Field(min_length=1, max_length=300)
    filter: str | None = Field(default=None, max_length=500)

    @field_validator("filter", mode="before")
    @classmethod
    def blank_filter_is_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


class MetricCreate(MetricIn):
    name: str = Field(pattern=NAME_PATTERN)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name", mode="before")
    @classmethod
    def normalise_name(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class MetricVersionCreate(MetricIn):
    description: str | None = Field(default=None, max_length=500)


class MetricValidateOut(BaseModel):
    valid: bool
    expression: str | None = None
    filter: str | None = None
    columns_used: list[str] = []
    aggregates_used: list[str] = []
    error: str | None = None


class MetricOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    expression: str
    filter: str | None = None
    version: int
    is_active: bool
    created_at: datetime


class MetricList(BaseModel):
    items: list[MetricOut]


def metric_out(metric) -> MetricOut:
    return MetricOut(
        id=metric.id,
        name=metric.name,
        description=metric.description,
        expression=metric.sql_expression,
        filter=metric.filter_sql,
        version=metric.version,
        is_active=metric.is_active,
        created_at=metric.created_at,
    )