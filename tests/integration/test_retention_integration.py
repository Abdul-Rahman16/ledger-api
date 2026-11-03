from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text, update

from core.db import SessionLocal
from core.storage import StorageError
from domain import metric_service
from domain.ingestion import ingest_dataset
from domain.models import Dataset, DatasetColumn, MetricDefinition, QueryLog
from domain.retention import delete_dataset, purge_expired_guest_datasets

CSV = b"order_id,amount,status\n1,10.5,completed\n2,20.0,completed\n"


class FakeStorage:
    def __init__(self):
        self.objects = {}
        self.fail_put = False
        self.fail_delete = False

    def put(self, key, data, content_type=None):
        if self.fail_put:
            raise StorageError("put failed")
        self.objects[key] = data

    def get(self, key):
        return self.objects[key]

    def delete(self, key):
        if self.fail_delete:
            raise StorageError("delete failed")
        self.objects.pop(key, None)


def naive_utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


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


def make_dataset(db, storage, user_id=None, age_hours=0):
    dataset = ingest_dataset(db, "orders.csv", CSV, user_id=user_id, storage=storage)
    db.created.append(dataset.id)
    if age_hours:
        db.execute(
            update(Dataset)
            .where(Dataset.id == dataset.id)
            .values(created_at=naive_utc_now() - timedelta(hours=age_hours))
        )
        db.commit()
    return dataset


def dataset_exists(db, dataset_id):
    return db.execute(select(func.count()).select_from(Dataset).where(Dataset.id == dataset_id)).scalar() == 1


def table_exists(db, table_name):
    return db.execute(text("select to_regclass(:name)"), {"name": f'public."{table_name}"'}).scalar() is not None


def row_count(db, model, dataset_id):
    return db.execute(select(func.count()).select_from(model).where(model.dataset_id == dataset_id)).scalar()


def test_ingestion_keeps_a_raw_copy_when_storage_is_configured(db):
    storage = FakeStorage()
    dataset = make_dataset(db, storage)
    assert dataset.status == "ready"
    assert dataset.storage_key == f"raw/guest/{dataset.id}/orders.csv"
    assert storage.objects[dataset.storage_key] == CSV


def test_a_storage_outage_does_not_fail_the_upload(db):
    storage = FakeStorage()
    storage.fail_put = True
    dataset = make_dataset(db, storage)
    assert dataset.status == "ready" and dataset.storage_key is None
    assert storage.objects == {}


def test_purge_deletes_expired_guest_datasets_completely(db):
    storage = FakeStorage()
    old = make_dataset(db, storage, age_hours=48)
    metric_service.create_metric(db, old, "total", "Sum of amounts", "SUM(amount)", None)
    db.add(QueryLog(dataset_id=old.id, question="q", status="answered"))
    db.commit()
    old_id, old_table, old_key = old.id, old.table_name, old.storage_key

    report = purge_expired_guest_datasets(db, storage, older_than=timedelta(hours=24), only_ids=[old_id])

    assert (report.datasets_deleted, report.objects_deleted, report.errors, report.candidates) == (1, 1, 0, 1)
    assert not dataset_exists(db, old_id)
    assert not table_exists(db, old_table)
    assert old_key not in storage.objects
    for model in (MetricDefinition, QueryLog, DatasetColumn):
        assert row_count(db, model, old_id) == 0


def test_purge_leaves_recent_guest_and_owned_datasets_alone(db):
    storage = FakeStorage()
    recent = make_dataset(db, storage, age_hours=1)
    owned = make_dataset(db, storage, user_id="user-keep", age_hours=48)
    report = purge_expired_guest_datasets(
        db, storage, older_than=timedelta(hours=24), only_ids=[recent.id, owned.id]
    )
    assert (report.datasets_deleted, report.candidates) == (0, 0)
    for dataset in (recent, owned):
        assert dataset_exists(db, dataset.id) and table_exists(db, dataset.table_name)
        assert dataset.storage_key in storage.objects


def test_a_failed_object_delete_keeps_the_dataset_for_the_next_run(db):
    storage = FakeStorage()
    old = make_dataset(db, storage, age_hours=48)
    old_id, old_table, old_key = old.id, old.table_name, old.storage_key

    storage.fail_delete = True
    report = purge_expired_guest_datasets(db, storage, older_than=timedelta(hours=24), only_ids=[old_id])
    assert (report.datasets_deleted, report.errors) == (0, 1)
    assert dataset_exists(db, old_id) and table_exists(db, old_table) and old_key in storage.objects

    storage.fail_delete = False
    report = purge_expired_guest_datasets(db, storage, older_than=timedelta(hours=24), only_ids=[old_id])
    assert (report.datasets_deleted, report.errors) == (1, 0)
    assert not dataset_exists(db, old_id) and old_key not in storage.objects


def test_batch_size_limits_one_sweep(db):
    storage = FakeStorage()
    ids = [make_dataset(db, storage, age_hours=48).id for _ in range(3)]
    first = purge_expired_guest_datasets(db, storage, older_than=timedelta(hours=24), only_ids=ids, batch_size=2)
    assert (first.datasets_deleted, first.candidates) == (2, 2)
    second = purge_expired_guest_datasets(db, storage, older_than=timedelta(hours=24), only_ids=ids, batch_size=2)
    assert (second.datasets_deleted, second.candidates) == (1, 1)


def test_dry_run_reports_candidates_without_deleting(db):
    storage = FakeStorage()
    old = make_dataset(db, storage, age_hours=48)
    report = purge_expired_guest_datasets(
        db, storage, older_than=timedelta(hours=24), only_ids=[old.id], dry_run=True
    )
    assert (report.candidates, report.datasets_deleted) == (1, 0)
    assert dataset_exists(db, old.id) and old.storage_key in storage.objects