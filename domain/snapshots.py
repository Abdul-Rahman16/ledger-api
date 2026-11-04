from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Collection

import pandas as pd
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from core.logging import log
from domain import dataset_service, metric_service
from domain.freshness import needs_metric_refresh, profile_fingerprint
from domain.models import Dataset, MetricSnapshot, QualitySnapshot
from domain.profiling import profile_dataframe, quality_score
from domain.query_builder import TABLE_RE, QueryRejected, QuerySpec, build_query
from domain.query_executor import QueryExecutionError, execute_readonly
from domain.query_result import ResultInvalid, validate_result


@dataclass(frozen=True)
class ReprofileReport:
    candidates: int
    profiled: int
    changed: int
    failed: int


@dataclass(frozen=True)
class MetricSnapshotReport:
    datasets: int
    computed: int  # snapshots stored with status ok or empty
    skipped: int  # metrics whose latest snapshot is still fresh
    failed: int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # timestamps are stored as naive UTC


# ---------- re-profiling ----------
def profile_table(db: Session, dataset: Dataset) -> tuple[list[dict[str, Any]], int, float]:
    table_name = dataset.table_name
    if not table_name or not TABLE_RE.match(table_name):
        raise ValueError("the dataset has no data table")
    frame = pd.read_sql_query(text(f'SELECT * FROM "{table_name}"'), db.connection())
    if frame.empty:
        raise ValueError("the dataset table is empty")
    columns = profile_dataframe(frame)
    return columns, len(frame), float(quality_score(columns, 0, len(frame)))


def reprofile_dataset(db: Session, dataset: Dataset, now: datetime) -> QualitySnapshot:
    dataset_id = dataset.id
    columns, row_count, score = profile_table(db, dataset)
    previous = db.execute(
        select(QualitySnapshot)
        .where(QualitySnapshot.dataset_id == dataset_id)
        .order_by(QualitySnapshot.taken_at.desc())
        .limit(1)
    ).scalars().first()

    fingerprint = profile_fingerprint(row_count, columns)
    snapshot = QualitySnapshot(
        dataset_id=dataset_id,
        taken_at=now,
        row_count=row_count,
        column_count=len(columns),
        quality_score=score,
        quality_delta=round(score - previous.quality_score, 2) if previous else None,
        row_delta=row_count - previous.row_count if previous else None,
        fingerprint=fingerprint,
        changed=(fingerprint != previous.fingerprint) if previous else None,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def reprofile_stale_datasets(
    db: Session,
    *,
    stale_after: timedelta,
    limit: int = 20,
    now: datetime | None = None,
    only_ids: Collection | None = None,
) -> ReprofileReport:
    """Re-profile ready datasets never profiled, or last profiled more than `stale_after` ago."""
    current = now or _utc_now()
    cutoff = current - stale_after

    latest = (
        select(QualitySnapshot.dataset_id.label("dataset_id"), func.max(QualitySnapshot.taken_at).label("last_taken"))
        .group_by(QualitySnapshot.dataset_id)
        .subquery()
    )
    query = (
        select(Dataset)
        .outerjoin(latest, latest.c.dataset_id == Dataset.id)
        .where(Dataset.status == "ready", or_(latest.c.last_taken.is_(None), latest.c.last_taken < cutoff))
    )
    if only_ids is not None:
        query = query.where(Dataset.id.in_(list(only_ids)))
    datasets = db.execute(
        query.order_by(latest.c.last_taken.asc().nulls_first(), Dataset.created_at).limit(limit)
    ).scalars().all()

    profiled = changed = failed = 0
    for dataset in datasets:
        dataset_id = dataset.id
        try:
            snapshot = reprofile_dataset(db, dataset, current)
            profiled += 1
            if snapshot.changed:
                changed += 1
        except Exception as exc:  # one broken dataset must not stop the sweep
            db.rollback()
            failed += 1
            log.error("reprofile_failed", dataset_id=str(dataset_id), error=type(exc).__name__)
    return ReprofileReport(len(datasets), profiled, changed, failed)


# ---------- metric snapshots ----------
def compute_metric_value(dataset: Dataset, metric: Any, columns: dict[str, str]) -> tuple[str, float | None]:
    """The metric's headline value through the same governed pipeline as every query."""
    try:
        built = build_query(QuerySpec(metric=metric.name), metric, dataset.table_name, columns)
        names, rows = execute_readonly(built.sql, built.limit + 1)
        result = validate_result(names, rows, built)
    except (QueryRejected, QueryExecutionError, ResultInvalid):
        return "failed", None
    value = result.rows[0]["value"] if result.rows else None
    return ("ok" if value is not None else "empty"), value


def snapshot_stale_metrics(
    db: Session,
    *,
    refresh_after: timedelta,
    limit: int = 50,
    now: datetime | None = None,
    only_ids: Collection | None = None,
    max_datasets: int = 500,
) -> MetricSnapshotReport:
    """Store a new snapshot for each active metric that is new, whose data changed, or that went stale."""
    current = now or _utc_now()
    query = select(Dataset).where(Dataset.status == "ready")
    if only_ids is not None:
        query = query.where(Dataset.id.in_(list(only_ids)))
    datasets = db.execute(query.order_by(Dataset.created_at).limit(max_datasets)).scalars().all()

    computed = skipped = failed = 0
    for dataset in datasets:
        if computed + failed >= limit:
            break
        dataset_id = dataset.id
        try:
            metrics = metric_service.list_active(db, dataset_id)
            if not metrics:
                continue
            changed_at = db.execute(
                select(func.max(QualitySnapshot.taken_at)).where(
                    QualitySnapshot.dataset_id == dataset_id, QualitySnapshot.changed.is_(True)
                )
            ).scalar()
            columns: dict[str, str] | None = None

            for metric in metrics:
                last = db.execute(
                    select(func.max(MetricSnapshot.taken_at)).where(MetricSnapshot.metric_id == metric.id)
                ).scalar()
                reason = needs_metric_refresh(
                    last_taken_at=last, data_changed_at=changed_at, now=current, refresh_after=refresh_after
                )
                if reason is None:
                    skipped += 1
                    continue
                if computed + failed >= limit:
                    break
                if columns is None:
                    columns = {c.name: c.dtype for c in dataset_service.get_columns(db, dataset_id)}

                metric_id, metric_version = metric.id, metric.version
                status, value = compute_metric_value(dataset, metric, columns)
                db.add(
                    MetricSnapshot(
                        dataset_id=dataset_id,
                        metric_id=metric_id,
                        metric_version=metric_version,
                        taken_at=current,
                        value=value,
                        status=status,
                        row_count=dataset.row_count,
                    )
                )
                db.commit()
                if status == "failed":
                    failed += 1
                else:
                    computed += 1
        except Exception as exc:
            db.rollback()
            failed += 1
            log.error("metric_snapshot_failed", dataset_id=str(dataset_id), error=type(exc).__name__)
    return MetricSnapshotReport(len(datasets), computed, skipped, failed)