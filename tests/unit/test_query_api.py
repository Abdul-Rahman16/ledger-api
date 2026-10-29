import uuid
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.config import settings
from core.db import get_db
from core.ratelimit import limiter
from domain import dataset_service, query_service
from domain.query_builder import QueryRejected
from domain.query_executor import QueryExecutionError, QueryTimeout
from domain.query_result import ResultInvalid
from domain.query_service import QueryOutcome
from main import app

SECRET = "test-secret"
AUTH = {"X-User-Id": "user-1", "X-Internal-Secret": SECRET}


def make_dataset(user_id=None):
    return SimpleNamespace(id=uuid.uuid4(), user_id=user_id, status="ready", table_name="ds_" + "c" * 32)


def make_outcome():
    metric = SimpleNamespace(
        id=uuid.uuid4(),
        name="total_revenue",
        description=None,
        sql_expression='SUM("amount")',
        filter_sql="\"status\" = 'completed'",
        version=1,
        is_active=True,
        created_at=datetime(2026, 1, 1),
    )
    return QueryOutcome(
        query_id=uuid.uuid4(),
        metric=metric,
        display_sql='SELECT "region" AS "group_value" FROM "dataset" LIMIT 101',
        columns=["group_value", "value"],
        rows=[{"group_value": "North", "value": 165.5}],
        row_count=1,
        truncated=False,
        warnings=[],
    )


def fake_db():
    yield object()


@pytest.fixture
def dataset():
    return make_dataset()


@pytest.fixture
def client(monkeypatch, dataset):
    monkeypatch.setattr(settings, "internal_secret", SECRET)
    monkeypatch.setattr(settings, "query_rate_limit_per_minute", 100)
    monkeypatch.setattr(dataset_service, "get_dataset", lambda db, dataset_id: dataset)
    app.dependency_overrides[get_db] = fake_db
    limiter.reset()
    yield TestClient(app)
    app.dependency_overrides.clear()
    limiter.reset()


def url(dataset):
    return f"/datasets/{dataset.id}/query"


def test_query_returns_rows(client, dataset, monkeypatch):
    monkeypatch.setattr(query_service, "run_query", lambda *a, **k: make_outcome())
    response = client.post(url(dataset), json={"metric": "total_revenue", "group_by": "region"})
    assert response.status_code == 200
    body = response.json()
    assert body["rows"] == [{"group_value": "North", "value": 165.5}]
    assert body["metric"]["name"] == "total_revenue"
    assert body["metric"]["expression"] == 'SUM("amount")'
    assert '"dataset"' in body["sql"] and "ds_" not in body["sql"]
    assert body["truncated"] is False and body["row_count"] == 1


def test_spec_is_built_from_request(client, dataset, monkeypatch):
    captured = {}

    def fake_run(*args, **kwargs):
        captured["spec"] = args[3]
        return make_outcome()

    monkeypatch.setattr(query_service, "run_query", fake_run)
    response = client.post(
        url(dataset),
        json={
            "metric": " Total_Revenue ",
            "group_by": "order_date",
            "time_grain": "week",
            "date_column": "order_date",
            "date_from": "2026-01-05",
            "date_to": "2026-01-31",
            "order": "group_asc",
            "limit": 12,
        },
    )
    assert response.status_code == 200
    spec = captured["spec"]
    assert spec.metric == "total_revenue"
    assert spec.time_grain == "week" and spec.order == "group_asc" and spec.limit == 12
    assert spec.date_from == date(2026, 1, 5) and spec.date_to == date(2026, 1, 31)


def test_guest_and_user_identity_are_passed(client, dataset, monkeypatch):
    seen = []

    def fake_run(*args, **kwargs):
        seen.append(args[2])
        return make_outcome()

    monkeypatch.setattr(query_service, "run_query", fake_run)
    client.post(url(dataset), json={"metric": "total_revenue"})
    client.post(url(dataset), json={"metric": "total_revenue"}, headers=AUTH)
    assert seen == [None, "user-1"]


def test_blank_optional_strings_become_none(client, dataset, monkeypatch):
    captured = {}

    def fake_run(*args, **kwargs):
        captured["spec"] = args[3]
        return make_outcome()

    monkeypatch.setattr(query_service, "run_query", fake_run)
    client.post(url(dataset), json={"metric": "total_revenue", "group_by": "  ", "date_column": ""})
    assert captured["spec"].group_by is None and captured["spec"].date_column is None


def test_rejection_maps_to_422(client, dataset, monkeypatch):
    def boom(*args, **kwargs):
        raise QueryRejected("Unknown metric 'x'. Available metrics: total_revenue.")

    monkeypatch.setattr(query_service, "run_query", boom)
    response = client.post(url(dataset), json={"metric": "total_revenue"})
    assert response.status_code == 422
    assert "Available metrics" in response.json()["detail"]


def test_timeout_maps_to_504(client, dataset, monkeypatch):
    def boom(*args, **kwargs):
        raise QueryTimeout("The query took too long and was stopped.")

    monkeypatch.setattr(query_service, "run_query", boom)
    assert client.post(url(dataset), json={"metric": "total_revenue"}).status_code == 504


def test_execution_and_result_errors_map_to_500(client, dataset, monkeypatch):
    for error in (QueryExecutionError("The query could not be executed."), ResultInvalid("internal detail")):
        def boom(*args, _error=error, **kwargs):
            raise _error

        monkeypatch.setattr(query_service, "run_query", boom)
        response = client.post(url(dataset), json={"metric": "total_revenue"})
        assert response.status_code == 500
        assert "internal detail" not in response.text


def test_request_validation(client, dataset):
    bad_bodies = [
        {},
        {"metric": "Bad Name!"},
        {"metric": "m1", "time_grain": "hour"},
        {"metric": "m1", "date_from": "not-a-date"},
        {"metric": "m1", "limit": 0},
        {"metric": "m1", "limit": 1001},
        {"metric": "m1", "order": "random"},
    ]
    for body in bad_bodies:
        assert client.post(url(dataset), json=body).status_code == 422, body


def test_other_users_dataset_is_404(client, monkeypatch):
    owned = make_dataset(user_id="user-2")
    monkeypatch.setattr(dataset_service, "get_dataset", lambda db, dataset_id: owned)
    body = {"metric": "total_revenue"}
    assert client.post(url(owned), json=body, headers=AUTH).status_code == 404
    assert client.post(url(owned), json=body).status_code == 404


def test_unknown_dataset_is_404(client, monkeypatch):
    monkeypatch.setattr(dataset_service, "get_dataset", lambda db, dataset_id: None)
    response = client.post(f"/datasets/{uuid.uuid4()}/query", json={"metric": "total_revenue"})
    assert response.status_code == 404


def test_query_rate_limit_returns_429(client, dataset, monkeypatch):
    monkeypatch.setattr(settings, "query_rate_limit_per_minute", 1)
    monkeypatch.setattr(query_service, "run_query", lambda *a, **k: make_outcome())
    assert client.post(url(dataset), json={"metric": "total_revenue"}).status_code == 200
    assert client.post(url(dataset), json={"metric": "total_revenue"}).status_code == 429


def test_bad_internal_secret_is_rejected(client, dataset):
    headers = {"X-User-Id": "user-1", "X-Internal-Secret": "wrong"}
    assert client.post(url(dataset), json={"metric": "total_revenue"}, headers=headers).status_code == 401