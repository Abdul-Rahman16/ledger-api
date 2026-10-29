import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from domain import dataset_service, metric_service, query_service
from domain.metric_service import MetricNotFound
from domain.query_builder import QueryRejected, QuerySpec
from domain.query_executor import QueryTimeout
from domain.query_result import ResultInvalid

TABLE = "ds_" + "b" * 32
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
METRIC = SimpleNamespace(
    id=uuid.uuid4(),
    name="total_revenue",
    sql_expression='SUM("amount")',
    filter_sql="\"status\" = 'completed'",
)


class FakeDB:
    def __init__(self):
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_commit = False

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    def commit(self):
        if self.fail_commit:
            raise RuntimeError("db down")
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def make_dataset(status="ready"):
    return SimpleNamespace(id=uuid.uuid4(), table_name=TABLE, status=status)


@pytest.fixture
def env(monkeypatch):
    db = FakeDB()
    state = {"result": (["value"], [(Decimal("500.74"),)]), "error": None, "executed": []}

    def fake_execute(sql, max_rows, timeout_ms=5000):
        state["executed"].append((sql, max_rows))
        if state["error"] is not None:
            raise state["error"]
        return state["result"]

    monkeypatch.setattr(metric_service, "get_active", lambda db_, dataset_id, name: METRIC)
    monkeypatch.setattr(metric_service, "list_active", lambda db_, dataset_id: [METRIC])
    monkeypatch.setattr(dataset_service, "get_columns", lambda db_, dataset_id: COLUMNS)
    monkeypatch.setattr(query_service, "execute_readonly", fake_execute)
    return SimpleNamespace(db=db, state=state)


def test_successful_query_logs_and_hides_table_name(env):
    outcome = query_service.run_query(env.db, make_dataset(), None, QuerySpec(metric="total_revenue"))
    assert outcome.rows == [{"value": 500.74}]
    assert outcome.row_count == 1 and outcome.truncated is False
    assert '"dataset"' in outcome.display_sql and TABLE not in outcome.display_sql
    assert env.state["executed"][0][1] == 101  # limit 100 + 1 to detect truncation

    entry = env.db.added[0]
    assert entry.status == "answered" and entry.row_count == 1
    assert entry.matched_metric_id == METRIC.id
    assert TABLE in entry.generated_sql
    assert outcome.query_id == entry.id


def test_grouped_query_result(env):
    env.state["result"] = (
        ["group_value", "value"],
        [("East", Decimal("230.25")), ("South", Decimal("149.99"))],
    )
    outcome = query_service.run_query(
        env.db, make_dataset(), None, QuerySpec(metric="total_revenue", group_by="region")
    )
    assert outcome.columns == ["group_value", "value"]
    assert outcome.rows[0] == {"group_value": "East", "value": 230.25}


def test_unknown_metric_lists_available_metrics_and_logs_rejection(env, monkeypatch):
    def missing(db_, dataset_id, name):
        raise MetricNotFound("nope")

    monkeypatch.setattr(metric_service, "get_active", missing)
    with pytest.raises(QueryRejected) as info:
        query_service.run_query(env.db, make_dataset(), None, QuerySpec(metric="nope"))
    assert "Available metrics: total_revenue" in str(info.value)
    assert env.state["executed"] == []
    entry = env.db.added[0]
    assert entry.status == "rejected" and entry.matched_metric_id is None


def test_builder_rejection_is_logged_and_nothing_executes(env):
    with pytest.raises(QueryRejected):
        query_service.run_query(
            env.db, make_dataset(), None, QuerySpec(metric="total_revenue", group_by="nope")
        )
    assert env.state["executed"] == []
    entry = env.db.added[0]
    assert entry.status == "rejected"
    assert entry.matched_metric_id == METRIC.id
    assert entry.generated_sql is None


def test_dataset_not_ready_is_rejected(env):
    with pytest.raises(QueryRejected) as info:
        query_service.run_query(env.db, make_dataset(status="uploaded"), None, QuerySpec(metric="total_revenue"))
    assert "not ready" in str(info.value)
    assert env.db.added[0].status == "rejected"


def test_timeout_is_logged_as_failed(env):
    env.state["error"] = QueryTimeout("The query took too long and was stopped.")
    with pytest.raises(QueryTimeout):
        query_service.run_query(env.db, make_dataset(), None, QuerySpec(metric="total_revenue"))
    entry = env.db.added[0]
    assert entry.status == "failed"
    assert "too long" in entry.rejection_reason
    assert TABLE in entry.generated_sql


def test_invalid_result_is_logged_as_failed(env):
    env.state["result"] = (["wrong_column"], [])
    with pytest.raises(ResultInvalid):
        query_service.run_query(env.db, make_dataset(), None, QuerySpec(metric="total_revenue"))
    assert env.db.added[0].status == "failed"


def test_logging_failure_does_not_mask_the_result(env):
    env.db.fail_commit = True
    outcome = query_service.run_query(env.db, make_dataset(), None, QuerySpec(metric="total_revenue"))
    assert outcome.rows == [{"value": 500.74}]
    assert outcome.query_id is None
    assert env.db.rollbacks >= 1


def test_identity_and_question_are_recorded(env):
    query_service.run_query(
        env.db,
        make_dataset(),
        "user-1",
        QuerySpec(metric="total_revenue", date_column="order_date", date_from=date(2026, 1, 1)),
        question="What was revenue since January?",
    )
    query_service.run_query(env.db, make_dataset(), None, QuerySpec(metric="total_revenue", limit=5))
    asked, guest = env.db.added
    assert asked.user_id == "user-1" and asked.question == "What was revenue since January?"
    assert guest.user_id is None
    assert guest.question.startswith("structured query: metric=total_revenue")
    assert "limit=5" in guest.question