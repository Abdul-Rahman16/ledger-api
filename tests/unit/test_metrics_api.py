import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.config import settings
from core.db import get_db
from core.ratelimit import limiter
from domain import dataset_service, metric_service
from domain.metric_service import MetricConflict, MetricNotFound
from domain.metric_validator import MetricValidationError
from main import app

SECRET = "test-secret"
AUTH = {"X-User-Id": "user-1", "X-Internal-Secret": SECRET}
COLUMNS = [
    SimpleNamespace(name=name, dtype=dtype)
    for name, dtype in [
        ("order_id", "integer"),
        ("region", "text"),
        ("amount", "float"),
        ("order_date", "datetime"),
        ("status", "text"),
    ]
]
BODY = {"name": "total_revenue", "expression": "SUM(amount)", "filter": "status = 'completed'"}


def make_dataset(user_id=None, status="ready"):
    return SimpleNamespace(id=uuid.uuid4(), user_id=user_id, status=status)


def make_metric(name="total_revenue", version=1, is_active=True):
    return SimpleNamespace(
        id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        name=name,
        description=None,
        sql_expression='SUM("amount")',
        filter_sql="\"status\" = 'completed'",
        version=version,
        is_active=is_active,
        created_at=datetime(2026, 1, 1),
    )


def fake_db():
    yield object()


@pytest.fixture
def dataset():
    return make_dataset()


@pytest.fixture
def client(monkeypatch, dataset):
    monkeypatch.setattr(settings, "internal_secret", SECRET)
    monkeypatch.setattr(settings, "read_rate_limit_per_minute", 100)
    monkeypatch.setattr(settings, "metric_write_rate_limit_per_minute", 100)
    monkeypatch.setattr(dataset_service, "get_dataset", lambda db, dataset_id: dataset)
    monkeypatch.setattr(dataset_service, "get_columns", lambda db, dataset_id: COLUMNS)
    app.dependency_overrides[get_db] = fake_db
    limiter.reset()
    yield TestClient(app)
    app.dependency_overrides.clear()
    limiter.reset()


def base(dataset):
    return f"/datasets/{dataset.id}/metrics"


def test_validate_returns_canonical_sql(client, dataset):
    response = client.post(
        f"{base(dataset)}/validate",
        json={"expression": "sum(amount)", "filter": "status = 'completed'"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["expression"] == 'SUM("amount")'
    assert body["filter"] == "\"status\" = 'completed'"
    assert body["columns_used"] == ["amount", "status"]


def test_validate_reports_problems_without_erroring(client, dataset):
    response = client.post(f"{base(dataset)}/validate", json={"expression": "SUM(nope)"})
    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert "Unknown column" in response.json()["error"]


def test_validate_rejects_injection(client, dataset):
    response = client.post(
        f"{base(dataset)}/validate", json={"expression": "SUM(amount); DROP TABLE datasets"}
    )
    assert response.status_code == 200
    assert response.json()["valid"] is False


def test_validate_on_unready_dataset_returns_409(client, monkeypatch):
    unready = make_dataset(status="uploaded")
    monkeypatch.setattr(dataset_service, "get_dataset", lambda db, dataset_id: unready)
    response = client.post(f"/datasets/{unready.id}/metrics/validate", json={"expression": "COUNT(*)"})
    assert response.status_code == 409


def test_create_metric_returns_201(client, dataset, monkeypatch):
    captured = {}

    def fake_create(*args, **kwargs):
        captured["args"] = args
        return make_metric()

    monkeypatch.setattr(metric_service, "create_metric", fake_create)
    response = client.post(base(dataset), json=BODY)
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "total_revenue"
    assert body["expression"] == 'SUM("amount")'
    assert body["version"] == 1
    assert captured["args"][2] == "total_revenue"


def test_create_metric_rejects_bad_name(client, dataset):
    response = client.post(base(dataset), json=dict(BODY, name="Bad Name!"))
    assert response.status_code == 422


def test_create_metric_normalises_name_case(client, dataset, monkeypatch):
    captured = {}

    def fake_create(*args, **kwargs):
        captured["name"] = args[2]
        return make_metric()

    monkeypatch.setattr(metric_service, "create_metric", fake_create)
    assert client.post(base(dataset), json=dict(BODY, name="  Total_Revenue ")).status_code == 201
    assert captured["name"] == "total_revenue"


def test_validation_error_maps_to_422(client, dataset, monkeypatch):
    def boom(*args, **kwargs):
        raise MetricValidationError("Unknown column 'nope'.")

    monkeypatch.setattr(metric_service, "create_metric", boom)
    response = client.post(base(dataset), json=BODY)
    assert response.status_code == 422
    assert "Unknown column" in response.json()["detail"]


def test_conflict_maps_to_409(client, dataset, monkeypatch):
    def boom(*args, **kwargs):
        raise MetricConflict("Metric 'total_revenue' already exists.")

    monkeypatch.setattr(metric_service, "create_metric", boom)
    assert client.post(base(dataset), json=BODY).status_code == 409


def test_list_metrics(client, dataset, monkeypatch):
    monkeypatch.setattr(metric_service, "list_active", lambda db, dataset_id: [make_metric()])
    response = client.get(base(dataset))
    assert response.status_code == 200
    assert response.json()["items"][0]["name"] == "total_revenue"


def test_get_metric_found_and_missing(client, dataset, monkeypatch):
    monkeypatch.setattr(metric_service, "get_active", lambda db, dataset_id, name: make_metric(name))
    assert client.get(f"{base(dataset)}/total_revenue").status_code == 200

    def missing(db, dataset_id, name):
        raise MetricNotFound("Metric 'nope' does not exist.")

    monkeypatch.setattr(metric_service, "get_active", missing)
    assert client.get(f"{base(dataset)}/nope").status_code == 404


def test_list_versions(client, dataset, monkeypatch):
    versions = [make_metric(version=2), make_metric(version=1, is_active=False)]
    monkeypatch.setattr(metric_service, "list_versions", lambda db, dataset_id, name: versions)
    response = client.get(f"{base(dataset)}/total_revenue/versions")
    assert response.status_code == 200
    assert [item["version"] for item in response.json()["items"]] == [2, 1]
    assert response.json()["items"][1]["is_active"] is False


def test_add_version_returns_201(client, dataset, monkeypatch):
    monkeypatch.setattr(metric_service, "create_version", lambda *a, **k: make_metric(version=2))
    response = client.post(
        f"{base(dataset)}/total_revenue/versions",
        json={"expression": "SUM(amount)", "filter": "status <> 'refunded'"},
    )
    assert response.status_code == 201
    assert response.json()["version"] == 2


def test_retire_metric_returns_204(client, dataset, monkeypatch):
    monkeypatch.setattr(metric_service, "retire_metric", lambda db, dataset, name: None)
    response = client.delete(f"{base(dataset)}/total_revenue")
    assert response.status_code == 204


def test_other_users_dataset_is_404_on_every_route(client, monkeypatch):
    owned = make_dataset(user_id="user-2")
    monkeypatch.setattr(dataset_service, "get_dataset", lambda db, dataset_id: owned)
    root = f"/datasets/{owned.id}/metrics"
    calls = [
        ("get", root, None),
        ("get", f"{root}/total_revenue", None),
        ("get", f"{root}/total_revenue/versions", None),
        ("post", root, BODY),
        ("post", f"{root}/validate", {"expression": "COUNT(*)"}),
        ("post", f"{root}/total_revenue/versions", {"expression": "COUNT(*)"}),
        ("delete", f"{root}/total_revenue", None),
    ]
    for headers in (AUTH, {}):
        for method, url, body in calls:
            response = client.request(method, url, json=body, headers=headers)
            assert response.status_code == 404, (method, url, headers)


def test_unknown_dataset_is_404(client, monkeypatch):
    monkeypatch.setattr(dataset_service, "get_dataset", lambda db, dataset_id: None)
    assert client.get(f"/datasets/{uuid.uuid4()}/metrics").status_code == 404


def test_write_rate_limit_returns_429(client, dataset, monkeypatch):
    monkeypatch.setattr(settings, "metric_write_rate_limit_per_minute", 1)
    url = f"{base(dataset)}/validate"
    assert client.post(url, json={"expression": "COUNT(*)"}).status_code == 200
    assert client.post(url, json={"expression": "COUNT(*)"}).status_code == 429


def test_bad_internal_secret_is_rejected(client, dataset):
    headers = {"X-User-Id": "user-1", "X-Internal-Secret": "wrong"}
    assert client.get(base(dataset), headers=headers).status_code == 401