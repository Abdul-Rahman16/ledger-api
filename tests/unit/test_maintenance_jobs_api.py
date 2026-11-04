from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from core.config import settings
from core.db import get_db
from domain import snapshots
from main import app

SECRET = "test-secret"
HEADERS = {"X-Internal-Secret": SECRET}
REPROFILE = "/internal/maintenance/reprofile"
SNAPSHOT = "/internal/maintenance/snapshot-metrics"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "internal_secret", SECRET)
    monkeypatch.setattr(settings, "profile_stale_after_hours", 24)
    monkeypatch.setattr(settings, "metric_refresh_after_hours", 12)
    calls = {"reprofile": [], "snapshot": []}

    def fake_reprofile(db, **kwargs):
        calls["reprofile"].append(kwargs)
        return snapshots.ReprofileReport(candidates=5, profiled=4, changed=1, failed=0)

    def fake_snapshot(db, **kwargs):
        calls["snapshot"].append(kwargs)
        return snapshots.MetricSnapshotReport(datasets=3, computed=7, skipped=2, failed=1)

    monkeypatch.setattr(snapshots, "reprofile_stale_datasets", fake_reprofile)
    monkeypatch.setattr(snapshots, "snapshot_stale_metrics", fake_snapshot)
    app.dependency_overrides[get_db] = lambda: object()
    test_client = TestClient(app)
    test_client.calls = calls
    yield test_client
    app.dependency_overrides.clear()


def test_both_job_endpoints_require_the_internal_secret(client):
    for url in (REPROFILE, SNAPSHOT):
        assert client.post(url).status_code == 401
        assert client.post(url, headers={"X-Internal-Secret": "wrong"}).status_code == 401
    assert client.calls == {"reprofile": [], "snapshot": []}


def test_defaults_come_from_settings_and_reports_are_returned(client):
    response = client.post(REPROFILE, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"stale_after_hours": 24, "candidates": 5, "profiled": 4, "changed": 1, "failed": 0}
    assert client.calls["reprofile"][0] == {"stale_after": timedelta(hours=24), "limit": 20}

    response = client.post(SNAPSHOT, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"refresh_after_hours": 12, "datasets": 3, "computed": 7, "skipped": 2, "failed": 1}
    assert client.calls["snapshot"][0] == {"refresh_after": timedelta(hours=12), "limit": 50}


def test_overrides_are_applied_and_bounds_are_enforced(client):
    assert client.post(REPROFILE + "?stale_after_hours=1&limit=5", headers=HEADERS).status_code == 200
    assert client.calls["reprofile"][0] == {"stale_after": timedelta(hours=1), "limit": 5}
    assert client.post(SNAPSHOT + "?refresh_after_hours=2&limit=10", headers=HEADERS).status_code == 200
    assert client.calls["snapshot"][0] == {"refresh_after": timedelta(hours=2), "limit": 10}

    for url in (REPROFILE + "?limit=0", REPROFILE + "?limit=101", REPROFILE + "?stale_after_hours=0",
                REPROFILE + "?stale_after_hours=721", SNAPSHOT + "?limit=201", SNAPSHOT + "?refresh_after_hours=0"):
        assert client.post(url, headers=HEADERS).status_code == 422, url
    assert len(client.calls["reprofile"]) == 1 and len(client.calls["snapshot"]) == 1


def test_job_endpoints_are_not_listed_in_the_public_api_docs(client):
    paths = app.openapi()["paths"]
    assert REPROFILE not in paths and SNAPSHOT not in paths