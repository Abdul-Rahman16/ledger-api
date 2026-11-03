from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Collection

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from core.logging import log
from core.storage import Storage
from domain.models import Dataset, DatasetColumn, MetricDefinition, QueryLog
from domain.query_builder import TABLE_RE


@dataclass(frozen=True)
class PurgeReport:
    datasets_deleted: int
    objects_deleted: int
    errors: int
    candidates: int  # expired datasets found in this batch (what a dry run would delete)


def delete_dataset(db: Session, dataset: Dataset, storage: Storage | None) -> bool:
    """
    Remove a dataset completely: raw copy, data table, metrics, audit logs and metadata.
    The raw object goes first. If that fails the exception propagates, nothing else is deleted,
    and the dataset is retried on the next run (so no object is ever left without a pointer).
    Returns True if a raw object was deleted.
    """
    dataset_id = dataset.id
    table_name = dataset.table_name
    storage_key = dataset.storage_key

    object_deleted = False
    if storage is not None and storage_key:
        storage.delete(storage_key)
        object_deleted = True

    db.execute(delete(QueryLog).where(QueryLog.dataset_id == dataset_id))
    db.execute(delete(MetricDefinition).where(MetricDefinition.dataset_id == dataset_id))
    db.execute(delete(DatasetColumn).where(DatasetColumn.dataset_id == dataset_id))
    db.execute(delete(Dataset).where(Dataset.id == dataset_id))
    if table_name and TABLE_RE.match(table_name):
        db.execute(text(f'DROP TABLE IF EXISTS "{table_name}"'))
    db.commit()
    return object_deleted


def purge_expired_guest_datasets(
    db: Session,
    storage: Storage | None,
    *,
    older_than: timedelta,
    now: datetime | None = None,
    batch_size: int = 100,
    only_ids: Collection | None = None,  # restrict the sweep (used by tests and targeted cleanups)
    dry_run: bool = False,
) -> PurgeReport:
    """Delete guest datasets (user_id is NULL) older than `older_than`. Owned datasets are never touched."""
    current = now or datetime.now(timezone.utc).replace(tzinfo=None)  # created_at is stored as naive UTC
    cutoff = current - older_than

    query = select(Dataset).where(Dataset.user_id.is_(None), Dataset.created_at < cutoff)
    if only_ids is not None:
        query = query.where(Dataset.id.in_(list(only_ids)))
    expired = db.execute(query.order_by(Dataset.created_at).limit(batch_size)).scalars().all()

    if dry_run:
        return PurgeReport(0, 0, 0, len(expired))

    deleted = objects = errors = 0
    for dataset in expired:
        dataset_id = dataset.id
        try:
            if delete_dataset(db, dataset, storage):
                objects += 1
            deleted += 1
        except Exception as exc:  # one bad dataset must not stop the sweep
            db.rollback()
            errors += 1
            log.error("guest_purge_failed", dataset_id=str(dataset_id), error=type(exc).__name__)
    return PurgeReport(deleted, objects, errors, len(expired))