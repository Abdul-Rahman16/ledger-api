import uuid
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.config import settings
from core.db import get_db
from core.ratelimit import rate_limit
from core.security import Identity, get_identity
from domain import dataset_service, pipeline_status

router = APIRouter(prefix="/datasets/{dataset_id}/pipeline", tags=["pipeline"])

read_limit = rate_limit("read", "read_rate_limit_per_minute")


class Freshness(BaseModel):
    status: Literal["fresh", "stale", "never_profiled"]
    last_profiled_at: datetime | None = None
    stale_after_hours: int
    age_hours: float | None = None


class QualityPoint(BaseModel):
    taken_at: datetime
    row_count: int
    quality_score: float
    quality_delta: float | None = None
    row_delta: int | None = None
    changed: bool | None = None


class MetricPoint(BaseModel):
    taken_at: datetime
    value: float | None = None
    status: str


class MetricTrend(BaseModel):
    name: str
    version: int
    status: str | None = None
    taken_at: datetime | None = None
    latest_value: float | None = None
    previous_value: float | None = None
    change_pct: float | None = None
    history: list[MetricPoint]


class PipelineOut(BaseModel):
    dataset_id: uuid.UUID
    freshness: Freshness
    quality_history: list[QualityPoint]
    metrics: list[MetricTrend]


@router.get("", response_model=PipelineOut, dependencies=[Depends(read_limit)])
def get_pipeline_status(
    dataset_id: uuid.UUID,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    dataset = dataset_service.get_dataset(db, dataset_id)
    # 404 (not 403) so other people's datasets are indistinguishable from missing ones.
    if dataset is None or not dataset_service.can_access(dataset, identity.user_id):
        raise HTTPException(status_code=404, detail="Dataset not found.")
    data = pipeline_status.build_pipeline_status(
        db, dataset, stale_after=timedelta(hours=settings.profile_stale_after_hours)
    )
    return PipelineOut(dataset_id=dataset.id, **data)