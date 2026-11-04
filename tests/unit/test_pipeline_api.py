import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.config import settings
from core.db import get_db
from domain import dataset_service, pipeline_status
from main import app

SECRET = "test-secret"
AUTH = {"X-User-Id": "user-1", "X-Internal-Secret": SECRET}

STATUS = {
    "freshness": {
        "status": "fresh",
        "last_profiled_at": datetime(2026, 11, 4, 3, 17),
        "stale_after_hours": 24,
        "age_hours": 2.5,
    },
    "quality_history": [
        {"taken_at": datetime(2026, 11, 3, 3, 17), "row_count": 6, "quality_score": 100.0,
         "quality_delta": None, "row_delta": None, "changed": None},
        {"taken_at": datetime(2026, 11, 4, 3, 17), "row_count": 7, "quality_score": 98.5,
         "quality_delta": -1.5, "row_delta": 1, "changed": True},
    ],
    "metrics": [
        {"name": "total_revenue", "version": 1, "status": "ok", "taken_at": datetime(2026, 11, 4, 3, 18),
         "latest_value": 600.0, "previous_value": 500.0, "change_pct": 20.0,
         "history": [{"taken_at": datetime(2026, 11, 3, 3, 18), "value": 500.0, "status": "ok"},
                     {"taken_at": datetime(2026, 11, 4, 3, 18), "value": 600.0, "status": "ok"}]},
    ],
}


def make_dataset(user_id=None):
    return SimpleNamespace(id=uuid.uuid4(), user_id=user_id)


@pytest.fixture
def dataset():
    return make_dataset()


@pytest.fixture
def client(monkeypatch, dataset):
    monkeypatch.setattr(settings, "internal_secret", SECRET)
    monkeypatch.setattr(settings, "read_rate_limit_per_minute", 100)
    monkeypatch.setattr(dataset_service, "get_dataset", lambda db, dataset_id: dataset)
    app.dependency_overrides[get_db] = lambda: object()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_returns_freshness_quality_history_and_metric_trends(client, dataset, monkeypatch):
    seen = {}

    def fake_status(db, ds, **kwargs):
        seen.update(kwargs)
        return STATUS

    monkeypatch.setattr(pipeline_status, "build_pipeline_status", fake_status)
    response = client.get(f"/datasets/{dataset.id}/pipeline")
    assert response.status_code == 200
    body = response.json()
    assert body["dataset_id"] == str(dataset.id)
    assert body["freshness"]["status"] == "fresh" and body["freshness"]["stale_after_hours"] == 24
    assert [point["row_count"] for point in body["quality_history"]] == [6, 7]
    assert body["quality_history"][1]["changed"] is True and body["quality_history"][0]["changed"] is None
    trend = body["metrics"][0]
    assert trend["name"] == "total_revenue" and trend["change_pct"] == 20.0 and len(trend["history"]) == 2
    assert seen["stale_after"] == timedelta(hours=settings.profile_stale_after_hours)


def test_other_users_dataset_is_404(client, monkeypatch):
    owned = make_dataset(user_id="user-2")
    monkeypatch.setattr(dataset_service, "get_dataset", lambda db, dataset_id: owned)
    assert client.get(f"/datasets/{owned.id}/pipeline", headers=AUTH).status_code == 404
    assert client.get(f"/datasets/{owned.id}/pipeline").status_code == 404


def test_unknown_dataset_is_404(client, monkeypatch):
    monkeypatch.setattr(dataset_service, "get_dataset", lambda db, dataset_id: None)
    assert client.get(f"/datasets/{uuid.uuid4()}/pipeline").status_code == 404