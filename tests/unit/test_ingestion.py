import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.db import Base
from domain.ingestion import MAX_UPLOAD_BYTES, IngestionError, ingest_dataset, read_upload
from domain.models import Dataset, DatasetColumn


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_ingest_csv_profiles_cleans_and_loads_table(db_session):
    content = b"Order Total,Region\n10,north\n20,south\n20,south\n,east\n"
    dataset = ingest_dataset(db_session, "orders.csv", content)

    assert dataset.status == "ready"
    assert dataset.row_count == 3  # one exact duplicate removed
    assert dataset.column_count == 2
    assert 0 < dataset.quality_score < 100

    stored = db_session.execute(text(f"SELECT COUNT(*) FROM {dataset.table_name}")).scalar()
    assert stored == 3
    assert db_session.query(DatasetColumn).filter_by(dataset_id=dataset.id).count() == 2


def test_read_upload_parses_json():
    content = json.dumps([{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]).encode()
    df, source_type = read_upload("d.json", content)
    assert source_type == "json"
    assert len(df) == 2


def test_read_upload_rejects_unsupported_extension():
    with pytest.raises(IngestionError):
        read_upload("data.txt", b"hello")


def test_read_upload_rejects_empty_file():
    with pytest.raises(IngestionError):
        read_upload("data.csv", b"")


def test_read_upload_rejects_oversized_file():
    with pytest.raises(IngestionError):
        read_upload("data.csv", b"x" * (MAX_UPLOAD_BYTES + 1))


def test_file_with_no_usable_data_is_rejected_without_creating_a_dataset(db_session):
    with pytest.raises(IngestionError):
        ingest_dataset(db_session, "empty.csv", b"a,b\n,\n,\n")
    assert db_session.query(Dataset).count() == 0