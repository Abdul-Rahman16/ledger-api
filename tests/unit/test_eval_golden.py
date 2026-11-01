import json
import os
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from domain.metric_validator import validate_metric
from domain.query_builder import QuerySpec, build_query
from domain.resolver import MetricInfo, ResolverContext, interpret_reply
from evals import golden
from evals.build_golden import build_cases
from evals.golden import (
    CaseResult,
    Observed,
    evaluate_case,
    load_cases,
    rows_match,
    spec_to_dict,
    summarize,
    validate_case,
)
from evals.oracle import CSV_PATH, compute, load_rows

TABLE = "ds_" + "e" * 32
CASES = load_cases()


def context_for(case):
    today = date.fromisoformat(case["today"]) if "today" in case else golden.DEFAULT_TODAY
    metrics = [MetricInfo(m["name"], m["description"]) for m in golden.FIXTURE_METRICS]
    return ResolverContext(metrics=metrics, columns=golden.FIXTURE_COLUMNS, today=today)


def reply_text(case):
    reply = case["llm_reply"]
    return reply if isinstance(reply, str) else json.dumps(reply)


def spec_from_dict(data):
    return QuerySpec(
        metric=data["metric"],
        group_by=data.get("group_by"),
        time_grain=data.get("time_grain"),
        date_column=data.get("date_column"),
        date_from=date.fromisoformat(data["date_from"]) if data.get("date_from") else None,
        date_to=date.fromisoformat(data["date_to"]) if data.get("date_to") else None,
        order=data.get("order"),
        limit=data.get("limit") or 100,
    )


def case_by_id(case_id):
    return next(case for case in CASES if case["id"] == case_id)


# ---------- the golden file itself ----------
def test_golden_file_is_valid_and_reasonably_large():
    assert len(CASES) >= 30
    assert len({case["id"] for case in CASES}) == len(CASES)
    tags = {tag for case in CASES for tag in case["tags"]}
    assert tags == {"routing", "clarification", "safety"}
    assert sum(1 for case in CASES if case["live"]) >= 15


def test_committed_golden_file_matches_the_generator():
    assert CASES == build_cases(), "golden_cases.jsonl is stale: run python -m evals.build_golden"


def test_fixture_csv_matches_the_declared_columns():
    rows = load_rows()
    assert len(rows) == 32 and len({row["order_id"] for row in rows}) == 32
    assert {row["status"] for row in rows} == {"completed", "refunded", "pending"}
    header = Path(CSV_PATH).read_text(encoding="utf-8").splitlines()[0].split(",")
    assert header == list(golden.FIXTURE_COLUMNS)


def test_expected_rows_match_the_independent_oracle():
    checked = 0
    for case in CASES:
        expect = case["expect"]
        if "rows" not in expect:
            continue
        spec = expect["spec"]
        result = compute(
            spec["metric"],
            group_by=spec.get("group_by"),
            time_grain=spec.get("time_grain"),
            date_from=date.fromisoformat(spec["date_from"]) if spec.get("date_from") else None,
            date_to=date.fromisoformat(spec["date_to"]) if spec.get("date_to") else None,
            order=spec.get("order"),
            limit=spec.get("limit") or 100,
        )
        assert rows_match(expect["rows"], result), case["id"]
        checked += 1
    assert checked >= 20


def test_oracle_known_values():
    assert compute("total_revenue") == [{"value": 3733.68}]
    assert compute("order_count") == [{"value": 25}]
    assert compute("refunded_amount") == [{"value": 217.0}]
    assert [row["group_value"] for row in compute("total_revenue", group_by="region")] == [
        "East", "North", "South", "West"
    ]
    assert compute("order_count", date_from=date(2025, 1, 1), date_to=date(2025, 12, 31)) == [{"value": 0}]
    assert compute("total_revenue", date_from=date(2025, 1, 1), date_to=date(2025, 12, 31)) == [{"value": None}]


# ---------- the golden file through the real resolver and builder ----------
def test_every_case_resolves_exactly_as_expected():
    for case in CASES:
        spec, clarification = interpret_reply(reply_text(case), context_for(case))
        expect = case["expect"]
        if expect.get("status") == "needs_clarification":
            assert spec is None and clarification, case["id"]
            needle = expect.get("clarification_contains")
            if needle:
                assert needle.lower() in clarification.lower(), (case["id"], clarification)
        elif "spec" in expect:
            assert clarification is None, (case["id"], clarification)
            resolved = spec_to_dict(spec)
            for name, wanted in expect["spec"].items():
                assert resolved[name] == wanted, (case["id"], name, resolved[name], wanted)


def test_every_answered_case_builds_governed_safe_sql():
    built = 0
    for case in CASES:
        expect = case["expect"]
        if "spec" not in expect:
            continue
        resolved, _ = interpret_reply(reply_text(case), context_for(case))
        definition = next(m for m in golden.FIXTURE_METRICS if m["name"] == resolved.metric)
        validated = validate_metric(definition["expression"], definition["filter"], golden.FIXTURE_COLUMNS)
        metric = SimpleNamespace(sql_expression=validated.expression_sql, filter_sql=validated.filter_sql)
        query = build_query(resolved, metric, TABLE, golden.FIXTURE_COLUMNS)
        assert query.sql.startswith("SELECT ") and TABLE in query.sql, case["id"]
        built += 1
    assert built >= 20


def test_fixture_metrics_are_accepted_by_the_metric_validator():
    for definition in golden.FIXTURE_METRICS:
        validate_metric(definition["expression"], definition["filter"], golden.FIXTURE_COLUMNS)


# ---------- loading and validating cases ----------
def write_cases(lines):
    handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    handle.write("\n".join(lines) + "\n")
    handle.close()
    return Path(handle.name)


def good_case(**overrides):
    case = {
        "id": "x", "question": "total revenue?", "llm_reply": {"metric": "total_revenue"},
        "tags": ["routing"], "live": True, "expect": {"status": "answered"},
    }
    case.update(overrides)
    return case


def test_load_cases_rejects_bad_files():
    bad_files = {
        "invalid json": ["{not json"],
        "duplicate id": [json.dumps(good_case()), json.dumps(good_case())],
        "unknown key": [json.dumps(good_case(surprise=1))],
    }
    for name, lines in bad_files.items():
        path = write_cases(lines)
        try:
            load_cases(path)
        except ValueError:
            continue
        finally:
            os.unlink(path)
        raise AssertionError(f"Expected ValueError for {name}")


def test_validate_case_catches_mistakes():
    assert validate_case(good_case()) == []
    assert validate_case("nope")
    assert validate_case(good_case(question="hi"))
    assert validate_case(good_case(llm_reply=5))
    assert validate_case(good_case(tags=[]))
    assert validate_case(good_case(tags=["fast"]))
    assert validate_case(good_case(expect={}))
    assert validate_case(good_case(expect={"status": "answered", "status_in": ["answered"]}))
    assert validate_case(good_case(expect={"status": "maybe"}))
    assert validate_case(good_case(expect={"status_in": ["answered", "explode"]}))
    assert validate_case(good_case(expect={"status": "answered", "spec": {"sql": "x"}}))
    assert validate_case(good_case(expect={"status": "needs_clarification", "spec": {"metric": "m"}}))
    assert validate_case(good_case(expect={"status": "answered", "bogus": 1}))


# ---------- scoring ----------
def answered_observed(**overrides):
    data = dict(
        status="answered",
        spec={"metric": "total_revenue", "group_by": "region", "limit": 100},
        rows=[{"group_value": "East", "value": 2111.25}, {"group_value": "North", "value": 832.84}],
        warnings=[],
    )
    data.update(overrides)
    return Observed(**data)


ROUTING_CASE = good_case(
    expect={
        "status": "answered",
        "spec": {"metric": "total_revenue", "group_by": "region"},
        "rows": [{"group_value": "East", "value": 2111.25}, {"group_value": "North", "value": 832.84}],
    }
)


def test_evaluate_case_passes_a_correct_observation():
    result = evaluate_case(ROUTING_CASE, answered_observed(), "offline")
    assert result.passed and result.failures == [] and result.status_ok
    assert result.spec_fields == {"metric": True, "group_by": True}


def test_evaluate_case_reports_each_kind_of_failure():
    wrong_group = evaluate_case(ROUTING_CASE, answered_observed(spec={"metric": "total_revenue", "group_by": "product"}), "live")
    assert not wrong_group.passed and wrong_group.spec_fields == {"metric": True, "group_by": False}
    assert any("spec.group_by" in failure for failure in wrong_group.failures)

    wrong_status = evaluate_case(ROUTING_CASE, Observed(status="needs_clarification", clarification="?"), "live")
    assert not wrong_status.status_ok and wrong_status.spec_fields == {"metric": False, "group_by": False}

    wrong_rows = evaluate_case(ROUTING_CASE, answered_observed(rows=[{"group_value": "East", "value": 1.0}]), "offline")
    assert not wrong_rows.passed and any("rows were" in failure for failure in wrong_rows.failures)

    errored = evaluate_case(ROUTING_CASE, Observed(status="error", error="QueryRejected: boom"), "offline")
    assert not errored.passed and any("raised an error" in failure for failure in errored.failures)


def test_row_comparison_uses_a_tolerance_and_respects_order_and_types():
    want = [{"group_value": "East", "value": 100.0}, {"group_value": "West", "value": 50.0}]
    assert rows_match(want, [{"group_value": "East", "value": 100.004}, {"group_value": "West", "value": 50}])
    assert not rows_match(want, [{"group_value": "East", "value": 100.5}, {"group_value": "West", "value": 50}])
    assert not rows_match(want, list(reversed(want)))
    assert not rows_match(want, want[:1])
    assert not rows_match(want, None)
    assert not rows_match([{"value": None}], [{"value": 0}])
    assert rows_match([{"value": None}], [{"value": None}])
    assert not rows_match([{"value": 1}], [{"value": 1, "extra": 2}])


def test_clarification_text_is_only_checked_offline():
    case = good_case(expect={"status": "needs_clarification", "clarification_contains": "profit"})
    observed = Observed(status="needs_clarification", clarification="Which metric do you mean?")
    assert not evaluate_case(case, observed, "offline").passed
    assert evaluate_case(case, observed, "live").passed
    assert evaluate_case(case, Observed(status="needs_clarification", clarification="No PROFIT metric."), "offline").passed


def test_status_in_and_warnings_checks():
    case = good_case(expect={"status_in": ["answered", "needs_clarification"]})
    assert evaluate_case(case, Observed(status="answered"), "live").passed
    assert evaluate_case(case, Observed(status="needs_clarification"), "live").passed
    assert not evaluate_case(case, Observed(status="error", error="x"), "live").passed

    warn_case = good_case(expect={"status": "answered", "warnings_contain": "empty"})
    assert evaluate_case(warn_case, answered_observed(warnings=["The metric is empty for every row."]), "offline").passed
    assert not evaluate_case(warn_case, answered_observed(), "offline").passed


def result(case_id, passed, tags, fields=None, status_ok=True, tokens=0, latency=0.0):
    return CaseResult(case_id, passed, [], "answered", status_ok, fields or {}, tags, tokens, latency)


def test_summary_counts_pass_rate_and_tags():
    results = [
        result("a", True, ["routing"]),
        result("b", False, ["routing", "safety"]),
        result("c", True, ["clarification"]),
        result("d", True, ["safety"]),
    ]
    summary = summarize(results, "offline")
    assert (summary["cases"], summary["passed"], summary["failed"], summary["pass_rate"]) == (4, 3, 1, 0.75)
    assert summary["by_tag"] == {
        "routing": {"passed": 1, "total": 2},
        "safety": {"passed": 1, "total": 2},
        "clarification": {"passed": 1, "total": 1},
    }
    assert "routing" not in summary  # scripted replies say nothing about routing accuracy


def test_live_summary_reports_routing_accuracy_tokens_and_latency():
    results = [
        result("a", True, ["routing"], {"metric": True, "group_by": True}, tokens=100, latency=200.0),
        result("b", False, ["routing"], {"metric": True, "group_by": False}, tokens=150, latency=400.0),
        result("c", False, ["routing"], {"metric": False}, status_ok=False, tokens=50, latency=300.0),
        result("d", True, ["clarification"], {}, tokens=0, latency=100.0),
    ]
    summary = summarize(results, "live")
    routing = summary["routing"]
    assert routing["spec_cases"] == 3
    assert routing["field_accuracy"]["metric"] == {"correct": 2, "total": 3, "accuracy": 0.6667}
    assert routing["field_accuracy"]["group_by"] == {"correct": 1, "total": 2, "accuracy": 0.5}
    assert routing["full_spec_match"] == 0.3333
    assert routing["status_accuracy"] == 0.75
    assert summary["tokens_total"] == 300 and summary["latency_ms_avg"] == 250.0
    assert summarize([], "live")["pass_rate"] == 0.0