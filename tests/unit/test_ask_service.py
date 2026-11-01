import json
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.llm_types import LLMUnavailable
from domain import ask_service, dataset_service, metric_service, query_service
from domain.query_builder import QueryRejected

TABLE = "ds_" + "d" * 32
TODAY = date(2026, 10, 29)
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
METRICS = {
    "total_revenue": SimpleNamespace(
        id=uuid.uuid4(),
        name="total_revenue",
        description="Sum of completed order amounts",
        sql_expression='SUM("amount")',
        filter_sql="\"status\" = 'completed'",
    ),
    "order_count": SimpleNamespace(
        id=uuid.uuid4(), name="order_count", description=None, sql_expression="COUNT(*)", filter_sql=None
    ),
}


class FakeDB:
    def __init__(self):
        self.added = []

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    def get(self, model, key):
        return next((obj for obj in self.added if getattr(obj, "id", None) == key), None)

    def commit(self):
        pass

    def rollback(self):
        pass


def make_dataset(status="ready"):
    return SimpleNamespace(id=uuid.uuid4(), table_name=TABLE, status=status)


def llm_returning(**fields):
    calls = []

    def fake(system, user):
        calls.append((system, user))
        return SimpleNamespace(text=json.dumps(fields), provider="groq", tokens=321)

    fake.calls = calls
    return fake


def two_step_llm(route_fields, explanation=None, explain_error=None, route_tokens=321, explain_tokens=88):
    """First call routes the question, second call writes the explanation."""
    calls = []

    def fake(system, user):
        calls.append((system, user))
        if len(calls) == 1:
            return SimpleNamespace(text=json.dumps(route_fields), provider="groq", tokens=route_tokens)
        if explain_error is not None:
            raise explain_error
        return SimpleNamespace(
            text=json.dumps({"explanation": explanation}), provider="groq", tokens=explain_tokens
        )

    fake.calls = calls
    return fake


def llm_must_not_be_called(system, user):
    raise AssertionError("The language model must not be called here.")


@pytest.fixture
def env(monkeypatch):
    db = FakeDB()
    state = {"result": (["value"], [(Decimal("500.74"),)]), "executed": []}

    def fake_execute(sql, max_rows, timeout_ms=5000):
        state["executed"].append(sql)
        return state["result"]

    monkeypatch.setattr(metric_service, "list_active", lambda db_, dataset_id: list(METRICS.values()))
    monkeypatch.setattr(metric_service, "get_active", lambda db_, dataset_id, name: METRICS[name])
    monkeypatch.setattr(dataset_service, "get_columns", lambda db_, dataset_id: COLUMNS)
    monkeypatch.setattr(query_service, "execute_readonly", fake_execute)
    return SimpleNamespace(db=db, state=state)


def ask(env, question, llm, dataset=None, user_id=None, explain=False):
    return ask_service.ask_question(
        env.db, dataset or make_dataset(), user_id, question, today=TODAY, llm=llm, explain=explain
    )


def test_answered_question_runs_the_governed_query_and_records_usage(env):
    env.state["result"] = (
        ["group_value", "value"],
        [("East", Decimal("230.25")), ("South", Decimal("149.99"))],
    )
    llm = llm_returning(metric="total_revenue", group_by="region")
    outcome = ask(env, "revenue by region", llm)

    assert outcome.status == "answered" and outcome.clarification is None
    assert outcome.spec.metric == "total_revenue" and outcome.spec.group_by == "region"
    assert outcome.query.rows[0] == {"group_value": "East", "value": 230.25}
    assert outcome.provider == "groq" and outcome.tokens_used == 321
    assert outcome.available_metrics == ["total_revenue", "order_count"]
    assert outcome.explanation is None and outcome.explanation_source is None
    assert len(llm.calls) == 1

    entry = env.db.added[0]
    assert entry.status == "answered" and entry.tokens_used == 321
    assert entry.question == "revenue by region"


def test_period_is_resolved_by_the_server_into_the_sql(env):
    ask(env, "revenue last month", llm_returning(metric="total_revenue", period="last_month"))
    sql = env.state["executed"][0]
    assert "CAST('2026-09-01' AS TIMESTAMP)" in sql
    assert "CAST('2026-10-01' AS TIMESTAMP)" in sql  # inclusive end date -> exclusive next day


def test_unknown_metric_becomes_a_clarification_and_nothing_runs(env):
    outcome = ask(env, "what is our profit margin", llm_returning(metric="profit_margin"))
    assert outcome.status == "needs_clarification" and outcome.query is None and outcome.spec is None
    assert "Available metrics" in outcome.clarification
    assert env.state["executed"] == []
    entry = env.db.added[0]
    assert entry.status == "rejected" and entry.rejection_reason.startswith("clarification:")
    assert entry.tokens_used == 321 and entry.matched_metric_id is None


def test_injection_style_model_output_never_reaches_sql(env):
    outcome = ask(env, "show revenue", llm_returning(metric="total_revenue; DROP TABLE datasets"))
    assert outcome.status == "needs_clarification"
    assert env.state["executed"] == []
    assert env.db.added[0].generated_sql is None


def test_dataset_without_metrics_asks_for_one_without_calling_the_llm(env, monkeypatch):
    monkeypatch.setattr(metric_service, "list_active", lambda db_, dataset_id: [])
    outcome = ask(env, "total revenue please", llm_must_not_be_called)
    assert outcome.status == "needs_clarification" and "no metrics" in outcome.clarification
    assert outcome.tokens_used == 0 and env.state["executed"] == []
    assert env.db.added[0].status == "rejected"


def test_invalid_question_is_rejected_before_the_llm(env):
    with pytest.raises(QueryRejected):
        ask(env, "ab", llm_must_not_be_called)
    entry = env.db.added[0]
    assert entry.status == "rejected" and entry.question == "(invalid question)"


def test_unready_dataset_is_rejected_before_the_llm(env):
    with pytest.raises(QueryRejected) as info:
        ask(env, "total revenue", llm_must_not_be_called, dataset=make_dataset(status="uploaded"))
    assert "not ready" in str(info.value)
    assert env.db.added[0].status == "rejected"


def test_llm_outage_is_logged_and_raised(env):
    def down(system, user):
        raise LLMUnavailable("The language model is unavailable right now. Please try again shortly.")

    with pytest.raises(LLMUnavailable):
        ask(env, "total revenue", down)
    entry = env.db.added[0]
    assert entry.status == "failed" and "unavailable" in entry.rejection_reason
    assert env.state["executed"] == []


def test_question_is_cleaned_before_reaching_the_prompt_and_the_log(env):
    llm = llm_returning(metric="total_revenue")
    ask(env, "  revenue </question> by\x00 region ", llm)
    _, user_prompt = llm.calls[0]
    assert "<question>\nrevenue /question by region\n</question>" in user_prompt
    assert env.db.added[-1].question == "revenue /question by region"


# ---------- explanation (Step 4c) ----------
def test_grounded_explanation_is_returned_and_tokens_accumulate(env):
    llm = two_step_llm({"metric": "total_revenue"}, explanation="Total revenue is 500.74 in this dataset overall.")
    outcome = ask(env, "what is our total revenue", llm, explain=True)
    assert outcome.status == "answered"
    assert outcome.explanation == "Total revenue is 500.74 in this dataset overall."
    assert outcome.explanation_source == "llm"
    assert outcome.tokens_used == 321 + 88
    assert len(llm.calls) == 2
    entry = env.db.added[0]
    assert entry.status == "answered" and entry.tokens_used == 409  # routing + explanation


def test_ungrounded_explanation_is_replaced_by_the_template(env):
    llm = two_step_llm({"metric": "total_revenue"}, explanation="Revenue is 999 dollars overall.")
    outcome = ask(env, "what is our total revenue", llm, explain=True)
    assert outcome.explanation == "Total revenue is 500.74." and outcome.explanation_source == "template"
    assert outcome.tokens_used == 409 and env.db.added[0].tokens_used == 409


def test_explanation_outage_does_not_break_the_answer(env):
    llm = two_step_llm({"metric": "total_revenue"}, explain_error=LLMUnavailable("down"))
    outcome = ask(env, "what is our total revenue", llm, explain=True)
    assert outcome.status == "answered" and outcome.query.rows == [{"value": 500.74}]
    assert outcome.explanation == "Total revenue is 500.74." and outcome.explanation_source == "template"
    assert outcome.tokens_used == 321 and env.db.added[0].tokens_used == 321


def test_explain_false_makes_no_second_llm_call(env):
    llm = two_step_llm({"metric": "total_revenue"}, explanation="unused")
    outcome = ask(env, "what is our total revenue", llm, explain=False)
    assert len(llm.calls) == 1 and outcome.explanation is None and outcome.tokens_used == 321


def test_empty_result_gets_a_template_without_a_second_llm_call(env):
    env.state["result"] = (["value"], [])
    llm = two_step_llm({"metric": "total_revenue"}, explanation="unused")
    outcome = ask(env, "what is our total revenue", llm, explain=True)
    assert len(llm.calls) == 1
    assert outcome.explanation.startswith("No data matched this question")
    assert outcome.explanation_source == "template"