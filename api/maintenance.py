from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.config import settings
from core.db import get_db
from core.security import require_internal_secret
from core.storage import get_storage
from domain import retention, snapshots

# Not part of the public API: hidden from the docs and guarded by the internal secret.
router = APIRouter(
    prefix="/internal/maintenance",
    tags=["maintenance"],
    include_in_schema=False,
    dependencies=[Depends(require_internal_secret)],
)


class PurgeOut(BaseModel):
    older_than_hours: int
    dry_run: bool
    candidates: int
    datasets_deleted: int
    objects_deleted: int
    errors: int


class ReprofileOut(BaseModel):
    stale_after_hours: int
    candidates: int
    profiled: int
    changed: int
    failed: int


class SnapshotMetricsOut(BaseModel):
    refresh_after_hours: int
    datasets: int
    computed: int
    skipped: int
    failed: int


@router.post("/purge-guest-data", response_model=PurgeOut)
def purge_guest_data(
    older_than_hours: int | None = Query(default=None, ge=1, le=720),
    dry_run: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    hours = older_than_hours or settings.guest_retention_hours
    report = retention.purge_expired_guest_datasets(
        db, get_storage(), older_than=timedelta(hours=hours), dry_run=dry_run
    )
    return PurgeOut(
        older_than_hours=hours,
        dry_run=dry_run,
        candidates=report.candidates,
        datasets_deleted=report.datasets_deleted,
        objects_deleted=report.objects_deleted,
        errors=report.errors,
    )


@router.post("/reprofile", response_model=ReprofileOut)
def reprofile(
    stale_after_hours: int | None = Query(default=None, ge=1, le=720),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    hours = stale_after_hours or settings.profile_stale_after_hours
    report = snapshots.reprofile_stale_datasets(db, stale_after=timedelta(hours=hours), limit=limit)
    return ReprofileOut(
        stale_after_hours=hours,
        candidates=report.candidates,
        profiled=report.profiled,
        changed=report.changed,
        failed=report.failed,
    )


@router.post("/snapshot-metrics", response_model=SnapshotMetricsOut)
def snapshot_metrics(
    refresh_after_hours: int | None = Query(default=None, ge=1, le=720),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    hours = refresh_after_hours or settings.metric_refresh_after_hours
    report = snapshots.snapshot_stale_metrics(db, refresh_after=timedelta(hours=hours), limit=limit)
    return SnapshotMetricsOut(
        refresh_after_hours=hours,
        datasets=report.datasets,
        computed=report.computed,
        skipped=report.skipped,
        failed=report.failed,
    )