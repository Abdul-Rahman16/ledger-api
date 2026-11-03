from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.config import settings
from core.db import get_db
from core.security import require_internal_secret
from core.storage import get_storage
from domain import retention

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