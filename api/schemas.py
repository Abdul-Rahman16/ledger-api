import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ColumnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    position: int
    dtype: str
    null_pct: float
    unique_count: int | None = None
    stats: Any | None = None


class DatasetOut(BaseModel):
    """Deliberately excludes table_name and storage_key: those are server internals."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    source_type: str
    original_filename: str
    status: str
    row_count: int | None = None
    column_count: int | None = None
    quality_score: float | None = None
    created_at: datetime


class DatasetDetail(DatasetOut):
    columns: list[ColumnOut]


class DatasetList(BaseModel):
    items: list[DatasetOut]
    limit: int
    offset: int