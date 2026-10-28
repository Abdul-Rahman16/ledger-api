import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import datasets as datasets_api
from core.config import settings
from core.db import get_db
from core.ratelimit import SlidingWindowLimiter, limiter
from domain import dataset_service
from domain.ingestion import IngestionError
from main import app

SECRET = "test-secret"
AUTH = {"X-User-Id": "user-1", "X-Internal-Secret": SECRET}
CSV = {"file": ("sales.csv", b"a,b\n1,2\n", "text/csv")}


def make_dataset(user_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id,
        name="sales",
        source_type="csv",
        original_filename="sales.csv",
        table_name="ds_secret_internal_name",
        status="ready",
        row_count=4,
        column_count=2,
        quality_score=73.8,
        created_at=datetime(2026, 1, 1),
    )


def make_column():
    return SimpleNamespace(
        name="amount", position=0, dtype="float", null_pct=0.0, unique_count=4, stats={"min": 1.0}
    )


def fake_db():
    yield object()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "internal_secret", SECRET)
    monkeypatch.setattr(settings, "upload_rate_limit_per_minute", 100)
    monkeypatch.setattr(settings, "read_rate_limit_per_minute", 100)
    monkeypatch.setattr(dataset_service, "get_columns", lambda db, dataset_id: [make_column()])
    app.dependency_overrides[get_db] = fake_db
    limiter.reset()
    yield TestClient(app)
    app.dependency_overrides.clear()
    limiter.reset()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_guest_upload_succeeds_and_hides_internals(client, monkeypatch):
    monkeypatch.setattr(datasets_api, "ingest_dataset", lambda db, f, c, user_id=None: make_dataset(user_id))
    response = client.post("/datasets", files=CSV)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ready"
    assert body["columns"][0]["name"] == "amount"
    assert "table_name" not in body
    assert "storage_key" not in body


def test_authenticated_upload_passes_user_id(client, monkeypatch):
    captured = {}

    def fake_ingest(db, filename, content, user_id=None):
        captured["user_id"] = user_id
        captured["filename"] = filename
        return make_dataset(user_id)

    monkeypatch.setattr(datasets_api, "ingest_dataset", fake_ingest)
    response = client.post("/datasets", files=CSV, headers=AUTH)
    assert response.status_code == 201
    assert captured == {"user_id": "user-1", "filename": "sales.csv"}


def test_bad_internal_secret_is_rejected(client):
    headers = {"X-User-Id": "user-1", "X-Internal-Secret": "wrong"}
    assert client.post("/datasets", files=CSV, headers=headers).status_code == 401
    assert client.get("/datasets", headers=headers).status_code == 401


def test_missing_server_secret_fails_closed(client, monkeypatch):
    monkeypatch.setattr(settings, "internal_secret", "")
    headers = {"X-User-Id": "user-1", "X-Internal-Secret": ""}
    assert client.get("/datasets", headers=headers).status_code == 401


def test_ingestion_error_maps_to_422(client, monkeypatch):
    def boom(db, filename, content, user_id=None):
        raise IngestionError("Unsupported file type '.exe'. Use CSV, XLSX, or JSON.")

    monkeypatch.setattr(datasets_api, "ingest_dataset", boom)
    response = client.post("/datasets", files=CSV)
    assert response.status_code == 422
    assert "Unsupported file type" in response.json()["detail"]


def test_unexpected_error_maps_to_generic_500(client, monkeypatch):
    def boom(db, filename, content, user_id=None):
        raise RuntimeError("database password is hunter2")

    monkeypatch.setattr(datasets_api, "ingest_dataset", boom)
    response = client.post("/datasets", files=CSV)
    assert response.status_code == 500
    assert "hunter2" not in response.text


def test_upload_rate_limit_returns_429(client, monkeypatch):
    monkeypatch.setattr(settings, "upload_rate_limit_per_minute", 2)
    monkeypatch.setattr(datasets_api, "ingest_dataset", lambda db, f, c, user_id=None: make_dataset(user_id))
    assert client.post("/datasets", files=CSV).status_code == 201
    assert client.post("/datasets", files=CSV).status_code == 201
    third = client.post("/datasets", files=CSV)
    assert third.status_code == 429
    assert int(third.headers["Retry-After"]) >= 1


def test_guest_list_is_empty(client):
    response = client.get("/datasets")
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_authenticated_list_returns_own_datasets(client, monkeypatch):
    monkeypatch.setattr(
        dataset_service, "list_datasets", lambda db, user_id, limit, offset: [make_dataset(user_id)]
    )
    response = client.get("/datasets", headers=AUTH)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


def test_get_guest_dataset_is_accessible_by_id(client, monkeypatch):
    dataset = make_dataset(user_id=None)
    monkeypatch.setattr(dataset_service, "get_dataset", lambda db, dataset_id: dataset)
    response = client.get(f"/datasets/{dataset.id}")
    assert response.status_code == 200
    assert response.json()["columns"][0]["dtype"] == "float"


def test_get_other_users_dataset_returns_404(client, monkeypatch):
    dataset = make_dataset(user_id="user-2")
    monkeypatch.setattr(dataset_service, "get_dataset", lambda db, dataset_id: dataset)
    assert client.get(f"/datasets/{dataset.id}", headers=AUTH).status_code == 404
    assert client.get(f"/datasets/{dataset.id}").status_code == 404


def test_get_missing_dataset_returns_404(client, monkeypatch):
    monkeypatch.setattr(dataset_service, "get_dataset", lambda db, dataset_id: None)
    assert client.get(f"/datasets/{uuid.uuid4()}").status_code == 404


def test_invalid_uuid_returns_422(client):
    assert client.get("/datasets/not-a-uuid").status_code == 422


def test_sliding_window_limiter_recovers_after_window():
    now = [0.0]
    window_limiter = SlidingWindowLimiter(clock=lambda: now[0])
    assert window_limiter.hit("k", 2, 60) == (True, 0)
    assert window_limiter.hit("k", 2, 60) == (True, 0)
    allowed, retry_after = window_limiter.hit("k", 2, 60)
    assert allowed is False and retry_after >= 1
    now[0] = 61.0
    assert window_limiter.hit("k", 2, 60)[0] is True


def test_can_access_rules():
    guest_dataset = make_dataset(user_id=None)
    owned_dataset = make_dataset(user_id="user-1")
    assert dataset_service.can_access(guest_dataset, None) is True
    assert dataset_service.can_access(guest_dataset, "anyone") is True
    assert dataset_service.can_access(owned_dataset, "user-1") is True
    assert dataset_service.can_access(owned_dataset, "user-2") is False
    assert dataset_service.can_access(owned_dataset, None) is False