from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from api import maintenance as maintenance_api
from core.config import settings
from core.db import get_db
from domain import retention
from main import app

SECRET = "test-secret"
URL = "/internal/maintenance/purge-guest-data"
HEADERS = {"X-Internal-Secret": SECRET}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "internal_secret", SECRET)
    monkeypatch.setattr(settings, "guest_retention_hours", 24)
    storage = object()
    calls = []

    def fake_purge(db, passed_storage, **kwargs):
        calls.append((passed_storage, kwargs))
        return retention.PurgeReport(datasets_deleted=3, objects_deleted=2, errors=1, candidates=4)

    monkeypatch.setattr(maintenance_api, "get_storage", lambda: storage)
    monkeypatch.setattr(retention, "purge_expired_guest_datasets", fake_purge)
    app.dependency_overrides[get_db] = lambda: object()
    test_client = TestClient(app)
    test_client.calls = calls
    test_client.storage = storage
    yield test_client
    app.dependency_overrides.clear()


def test_requires_the_internal_secret(client):
    assert client.post(URL).status_code == 401
    assert client.post(URL, headers={"X-Internal-Secret": "wrong"}).status_code == 401
    assert client.post(URL, headers={"X-User-Id": "user-1"}).status_code == 401
    assert client.calls == []


def test_fails_closed_when_no_secret_is_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "internal_secret", "")
    assert client.post(URL, headers={"X-Internal-Secret": ""}).status_code == 401
    assert client.post(URL).status_code == 401
    assert client.calls == []


def test_purges_with_the_configured_default_retention(client):
    response = client.post(URL, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {
        "older_than_hours": 24, "dry_run": False, "candidates": 4,
        "datasets_deleted": 3, "objects_deleted": 2, "errors": 1,
    }
    storage, kwargs = client.calls[0]
    assert storage is client.storage
    assert kwargs == {"older_than": timedelta(hours=24), "dry_run": False}


def test_retention_and_dry_run_can_be_overridden_within_bounds(client):
    response = client.post(URL + "?older_than_hours=2&dry_run=true", headers=HEADERS)
    assert response.status_code == 200 and response.json()["dry_run"] is True
    assert client.calls[0][1] == {"older_than": timedelta(hours=2), "dry_run": True}
    assert client.post(URL + "?older_than_hours=0", headers=HEADERS).status_code == 422
    assert client.post(URL + "?older_than_hours=721", headers=HEADERS).status_code == 422
    assert len(client.calls) == 1


def test_endpoint_is_not_listed_in_the_public_api_docs(client):
    assert URL not in app.openapi()["paths"]