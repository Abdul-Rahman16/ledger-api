from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text, update

from core.db import SessionLocal
from domain import metric_service
from domain.ingestion import ingest_dataset
from domain.models import Dataset, MetricSnapshot, QualitySnapshot
from domain.pipeline_status import build_pipeline_status
from domain.retention import delete_dataset, purge_expired_guest_datasets
from domain.snapshots import reprofile_stale_datasets, snapshot_stale_metrics

CSV = b"order_id,amount,status\n1,10.5,completed\n2,20.0,completed\n"
DAY = timedelta(hours=24)
NEVER_FRESH = timedelta(0)


class NullStorage:
    def put(self, key, data, content_type=None):
        pass

    def get(self, key):
        return b""

    def delete(self, key):
        pass


def naive_utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def minutes(base, count):
    return base + timedelta(minutes=count)


@pytest.fixture
def db():
    session = SessionLocal()
    session.created = []
    yield session
    session.rollback()
    for dataset_id in session.created:
        leftover = session.execute(select(Dataset).where(Dataset.id == dataset_id)).scalar_one_or_none()
        if leftover is not None:
            delete_dataset(session, leftover, None)
    session.close()


def make_dataset(db, age_hours=0):
    dataset = ingest_dataset(db, "orders.csv", CSV, user_id=None, storage=NullStorage())
    db.created.append(dataset.id)
    if age_hours:
        db.execute(
            update(Dataset).where(Dataset.id == dataset.id)
            .values(created_at=naive_utc_now() - timedelta(hours=age_hours))
        )
        db.commit()
    return dataset


def insert_row(db, dataset, order_id, amount):
    table = dataset.table_name
    db.execute(
        text(f'INSERT INTO "{table}" (order_id, amount, status) VALUES (:i, :a, \'completed\')'),
        {"i": order_id, "a": amount},
    )
    db.commit()


def quality_snapshots(db, dataset_id):
    return db.execute(
        select(QualitySnapshot).where(QualitySnapshot.dataset_id == dataset_id).order_by(QualitySnapshot.taken_at)
    ).scalars().all()


def metric_snapshots(db, metric_id):
    return db.execute(
        select(MetricSnapshot).where(MetricSnapshot.metric_id == metric_id).order_by(MetricSnapshot.taken_at)
    ).scalars().all()


def count(db, model, dataset_id):
    return db.execute(select(func.count()).select_from(model).where(model.dataset_id == dataset_id)).scalar()


def test_first_reprofile_records_a_baseline_snapshot(db):
    dataset = make_dataset(db)
    dataset_id = dataset.id
    report = reprofile_stale_datasets(db, stale_after=DAY, now=naive_utc_now(), only_ids=[dataset_id])
    assert (report.candidates, report.profiled, report.changed, report.failed) == (1, 1, 0, 0)
    (snapshot,) = quality_snapshots(db, dataset_id)
    assert (snapshot.row_count, snapshot.column_count) == (2, 3)
    assert snapshot.quality_score > 0 and len(snapshot.fingerprint) == 64
    assert snapshot.quality_delta is None and snapshot.row_delta is None and snapshot.changed is None


def test_reprofiling_unchanged_data_shows_no_drift(db):
    dataset = make_dataset(db)
    dataset_id, base = dataset.id, naive_utc_now()
    reprofile_stale_datasets(db, stale_after=DAY, now=base, only_ids=[dataset_id])
    report = reprofile_stale_datasets(db, stale_after=NEVER_FRESH, now=minutes(base, 1), only_ids=[dataset_id])
    assert (report.profiled, report.changed) == (1, 0)
    first, second = quality_snapshots(db, dataset_id)
    assert second.fingerprint == first.fingerprint and second.changed is False
    assert second.quality_delta == 0.0 and second.row_delta == 0


def test_fresh_datasets_are_not_reprofiled_until_they_go_stale(db):
    dataset = make_dataset(db)
    dataset_id, base = dataset.id, naive_utc_now()
    reprofile_stale_datasets(db, stale_after=DAY, now=base, only_ids=[dataset_id])
    fresh = reprofile_stale_datasets(db, stale_after=DAY, now=base + timedelta(hours=1), only_ids=[dataset_id])
    assert fresh.candidates == 0
    stale = reprofile_stale_datasets(db, stale_after=DAY, now=base + timedelta(hours=25), only_ids=[dataset_id])
    assert (stale.candidates, stale.profiled) == (1, 1)


def test_data_changes_are_detected_as_drift(db):
    dataset = make_dataset(db)
    dataset_id, base = dataset.id, naive_utc_now()
    reprofile_stale_datasets(db, stale_after=DAY, now=base, only_ids=[dataset_id])
    insert_row(db, dataset, 3, 10.0)
    report = reprofile_stale_datasets(db, stale_after=NEVER_FRESH, now=minutes(base, 1), only_ids=[dataset_id])
    assert (report.profiled, report.changed) == (1, 1)
    first, second = quality_snapshots(db, dataset_id)
    assert second.changed is True and second.row_delta == 1 and second.row_count == 3
    assert second.fingerprint != first.fingerprint


def test_metric_snapshots_follow_data_freshness(db):
    dataset = make_dataset(db)
    metric = metric_service.create_metric(db, dataset, "total", "Sum of amounts", "SUM(amount)", None)
    metric_id, ids, base = metric.id, [dataset.id], naive_utc_now()
    reprofile_stale_datasets(db, stale_after=DAY, now=base, only_ids=ids)

    first = snapshot_stale_metrics(db, refresh_after=DAY, now=minutes(base, 1), only_ids=ids)
    assert (first.computed, first.skipped, first.failed) == (1, 0, 0)
    again = snapshot_stale_metrics(db, refresh_after=DAY, now=minutes(base, 2), only_ids=ids)
    assert (again.computed, again.skipped) == (0, 1)

    insert_row(db, dataset, 3, 10.0)
    reprofile_stale_datasets(db, stale_after=NEVER_FRESH, now=minutes(base, 3), only_ids=ids)
    changed = snapshot_stale_metrics(db, refresh_after=DAY, now=minutes(base, 4), only_ids=ids)
    assert (changed.computed, changed.skipped) == (1, 0)

    stale = snapshot_stale_metrics(db, refresh_after=NEVER_FRESH, now=minutes(base, 5), only_ids=ids)
    assert stale.computed == 1
    assert [(s.value, s.status, s.metric_version) for s in metric_snapshots(db, metric_id)] == [
        (30.5, "ok", 1), (40.5, "ok", 1), (40.5, "ok", 1),
    ]


def test_empty_and_failed_metrics_are_recorded_not_hidden(db):
    dataset = make_dataset(db)
    table = dataset.table_name
    metric = metric_service.create_metric(
        db, dataset, "refunded", "Sum of refunded amounts", "SUM(amount)", "status = 'refunded'"
    )
    metric_id, ids, base = metric.id, [dataset.id], naive_utc_now()

    first = snapshot_stale_metrics(db, refresh_after=DAY, now=minutes(base, 1), only_ids=ids)
    assert (first.computed, first.failed) == (1, 0)

    db.execute(text(f'ALTER TABLE "{table}" DROP COLUMN amount'))
    db.commit()
    second = snapshot_stale_metrics(db, refresh_after=NEVER_FRESH, now=minutes(base, 2), only_ids=ids)
    assert (second.computed, second.failed) == (0, 1)
    assert [(s.status, s.value) for s in metric_snapshots(db, metric_id)] == [("empty", None), ("failed", None)]


def test_pipeline_status_summarises_freshness_quality_and_metrics(db):
    dataset = make_dataset(db)
    metric = metric_service.create_metric(db, dataset, "total", "Sum of amounts", "SUM(amount)", None)
    ids, base = [dataset.id], naive_utc_now()
    reprofile_stale_datasets(db, stale_after=DAY, now=base, only_ids=ids)
    reprofile_stale_datasets(db, stale_after=NEVER_FRESH, now=minutes(base, 1), only_ids=ids)
    snapshot_stale_metrics(db, refresh_after=DAY, now=minutes(base, 2), only_ids=ids)
    snapshot_stale_metrics(db, refresh_after=NEVER_FRESH, now=minutes(base, 3), only_ids=ids)

    status = build_pipeline_status(db, dataset, stale_after=DAY, now=minutes(base, 10))
    assert status["freshness"]["status"] == "fresh" and status["freshness"]["stale_after_hours"] == 24
    history = status["quality_history"]
    assert len(history) == 2 and history[0]["taken_at"] < history[1]["taken_at"]
    (trend,) = status["metrics"]
    assert trend["name"] == "total" and trend["latest_value"] == 30.5 and trend["previous_value"] == 30.5
    assert trend["change_pct"] == 0.0 and len(trend["history"]) == 2

    stale = build_pipeline_status(db, dataset, stale_after=DAY, now=base + timedelta(hours=48))
    assert stale["freshness"]["status"] == "stale"
    never = make_dataset(db)
    assert build_pipeline_status(db, never, stale_after=DAY, now=base)["freshness"]["status"] == "never_profiled"


def test_purging_a_dataset_removes_its_snapshots_too(db):
    dataset = make_dataset(db, age_hours=48)
    metric_service.create_metric(db, dataset, "total", "Sum of amounts", "SUM(amount)", None)
    dataset_id, base = dataset.id, naive_utc_now()
    reprofile_stale_datasets(db, stale_after=DAY, now=base, only_ids=[dataset_id])
    snapshot_stale_metrics(db, refresh_after=DAY, now=minutes(base, 1), only_ids=[dataset_id])
    assert count(db, QualitySnapshot, dataset_id) == 1 and count(db, MetricSnapshot, dataset_id) == 1

    report = purge_expired_guest_datasets(db, None, older_than=DAY, only_ids=[dataset_id])
    assert report.datasets_deleted == 1
    assert count(db, QualitySnapshot, dataset_id) == 0 and count(db, MetricSnapshot, dataset_id) == 0