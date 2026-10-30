import uuid
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.config import settings
from core.db import get_db
from core.llm_types import LLMUnavailable
from core.ratelimit import limiter
from domain import ask_service, dataset_service
from domain.ask_service import AskOutcome
from domain.query_builder import QueryRejected, QuerySpec
from domain.query_executor import QueryExecutionError, QueryTimeout
from domain.query_result import ResultInvalid
from domain.query_service import QueryOutcome
from main import app

SECRET = "test-secret"
AUTH = {"X-User-Id": "user-1", "X-Internal-Secret": SECRET}
QUESTION = {"question": "revenue by region last month"}


def make_dataset(user_id=None):
    return SimpleNamespace(id=uuid.uuid4(), user_id=user_id, status="ready", table_name="ds_" + "e" * 32)


def make_answered():
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
    query = QueryOutcome(
        query_id=uuid.uuid4(),
        metric=metric,
        display_sql='SELECT "region" AS "group_value" FROM "dataset" LIMIT 101',
        columns=["group_value", "value"],
        rows=[{"group_value": "North", "value": 165.5}],
        row_count=1,
        truncated=False,
        warnings=[],
    )
    spec = QuerySpec(
        metric="total_revenue",
        group_by="region",
        date_column="order_date",
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
        order="value_desc",
        limit=100,
    )
    return AskOutcome("answered", "revenue by region last month", None, spec, query, "groq", 321, ["total_revenue"])


def make_clarification():
    return AskOutcome(
        "needs_clarification", "churn rate", "Which metric do you mean?", None, None, "groq", 200,
        ["total_revenue", "order_count"],
    )


def fake_db():
    yield object()


@pytest.fixture
def dataset():
    return make_dataset()


@pytest.fixture
def client(monkeypatch, dataset):
    monkeypatch.setattr(settings, "internal_secret", SECRET)
    monkeypatch.setattr(settings, "ask_rate_limit_per_minute", 100)
    monkeypatch.setattr(dataset_service, "get_dataset", lambda db, dataset_id: dataset)
    app.dependency_overrides[get_db] = fake_db
    limiter.reset()
    yield TestClient(app)
    app.dependency_overrides.clear()
    limiter.reset()


def url(dataset):
    return f"/datasets/{dataset.id}/ask"


def test_answered_response_shows_interpretation_and_result(client, dataset, monkeypatch):
    monkeypatch.setattr(ask_service, "ask_question", lambda *a, **k: make_answered())
    response = client.post(url(dataset), json=QUESTION)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered" and body["clarification"] is None
    assert body["interpretation"]["metric"] == "total_revenue"
    assert body["interpretation"]["date_from"] == "2026-09-01"
    assert body["interpretation"]["order"] == "value_desc"
    assert body["result"]["rows"] == [{"group_value": "North", "value": 165.5}]
    assert '"dataset"' in body["result"]["sql"] and "ds_" not in body["result"]["sql"]
    assert body["provider"] == "groq" and body["tokens_used"] == 321
    assert body["available_metrics"] == ["total_revenue"]


def test_clarification_response_has_no_result(client, dataset, monkeypatch):
    monkeypatch.setattr(ask_service, "ask_question", lambda *a, **k: make_clarification())
    body = client.post(url(dataset), json={"question": "churn rate"}).json()
    assert body["status"] == "needs_clarification"
    assert body["clarification"] == "Which metric do you mean?"
    assert body["result"] is None and body["interpretation"] is None
    assert body["available_metrics"] == ["total_revenue", "order_count"]


def test_identity_is_passed_through(client, dataset, monkeypatch):
    seen = []

    def fake_ask(*args, **kwargs):
        seen.append((args[2], args[3]))
        return make_clarification()

    monkeypatch.setattr(ask_service, "ask_question", fake_ask)
    client.post(url(dataset), json=QUESTION)
    client.post(url(dataset), json=QUESTION, headers=AUTH)
    assert seen == [(None, QUESTION["question"]), ("user-1", QUESTION["question"])]


def test_rejection_maps_to_422(client, dataset, monkeypatch):
    def boom(*args, **kwargs):
        raise QueryRejected("Questions must be between 3 and 500 characters.")

    monkeypatch.setattr(ask_service, "ask_question", boom)
    response = client.post(url(dataset), json=QUESTION)
    assert response.status_code == 422 and "Questions must be" in response.json()["detail"]


def test_llm_outage_maps_to_503(client, dataset, monkeypatch):
    def boom(*args, **kwargs):
        raise LLMUnavailable("The language model is unavailable right now. Please try again shortly.")

    monkeypatch.setattr(ask_service, "ask_question", boom)
    response = client.post(url(dataset), json=QUESTION)
    assert response.status_code == 503 and "unavailable" in response.json()["detail"]


def test_execution_errors_map_to_504_and_500(client, dataset, monkeypatch):
    cases = [
        (QueryTimeout("The query took too long and was stopped."), 504),
        (QueryExecutionError("The query could not be executed."), 500),
        (ResultInvalid("internal detail"), 500),
    ]
    for error, expected in cases:
        def boom(*args, _error=error, **kwargs):
            raise _error

        monkeypatch.setattr(ask_service, "ask_question", boom)
        response = client.post(url(dataset), json=QUESTION)
        assert response.status_code == expected
        assert "internal detail" not in response.text


def test_question_length_is_validated(client, dataset):
    for body in ({}, {"question": ""}, {"question": "ab"}, {"question": "x" * 501}):
        assert client.post(url(dataset), json=body).status_code == 422, body


def test_other_users_dataset_is_404(client, monkeypatch):
    owned = make_dataset(user_id="user-2")
    monkeypatch.setattr(dataset_service, "get_dataset", lambda db, dataset_id: owned)
    assert client.post(url(owned), json=QUESTION, headers=AUTH).status_code == 404
    assert client.post(url(owned), json=QUESTION).status_code == 404


def test_unknown_dataset_is_404(client, monkeypatch):
    monkeypatch.setattr(dataset_service, "get_dataset", lambda db, dataset_id: None)
    assert client.post(f"/datasets/{uuid.uuid4()}/ask", json=QUESTION).status_code == 404


def test_ask_rate_limit_returns_429(client, dataset, monkeypatch):
    monkeypatch.setattr(settings, "ask_rate_limit_per_minute", 1)
    monkeypatch.setattr(ask_service, "ask_question", lambda *a, **k: make_clarification())
    assert client.post(url(dataset), json=QUESTION).status_code == 200
    assert client.post(url(dataset), json=QUESTION).status_code == 429


def test_bad_internal_secret_is_rejected(client, dataset):
    headers = {"X-User-Id": "user-1", "X-Internal-Secret": "wrong"}
    assert client.post(url(dataset), json=QUESTION, headers=headers).status_code == 401