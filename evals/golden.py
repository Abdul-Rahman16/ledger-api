"""
Golden questions: loading, scoring and summarising (pure Python, no database).

Each line of golden_cases.jsonl is one case:

  id, question          what the user asks
  llm_reply             the model output to replay in offline mode (object, or a raw string)
  today                 optional ISO date, used for relative periods ("last month")
  tags                  routing | clarification | safety
  live                  true if the case is also meaningful against a real model
  expect                what must be true:
      status | status_in          "answered" / "needs_clarification"
      spec                        resolved spec fields that must match (metric, group_by, ...)
      rows                        exact result rows, in order (values compared with a tolerance)
      clarification_contains      substring, checked in offline mode only
      warnings_contain            substring that must appear in a result warning
"""

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from evals.oracle import CSV_PATH  # noqa: F401  (re-exported for the runner)

CASES_PATH = Path(__file__).parent / "golden_cases.jsonl"
DEFAULT_TODAY = date(2026, 4, 15)  # "today" for offline runs unless a case sets its own
VALUE_TOLERANCE = 0.01

FIXTURE_COLUMNS = {
    "order_id": "integer",
    "region": "text",
    "product": "text",
    "amount": "float",
    "order_date": "datetime",
    "status": "text",
}
FIXTURE_METRICS = [
    {
        "name": "total_revenue",
        "description": "Sum of completed order amounts",
        "expression": "SUM(amount)",
        "filter": "status = 'completed'",
    },
    {
        "name": "order_count",
        "description": "Number of completed orders",
        "expression": "COUNT(*)",
        "filter": "status = 'completed'",
    },
    {
        "name": "avg_order_value",
        "description": "Average amount per completed order",
        "expression": "SUM(amount) / COUNT(DISTINCT order_id)",
        "filter": "status = 'completed'",
    },
    {
        "name": "refunded_amount",
        "description": "Sum of refunded order amounts",
        "expression": "SUM(amount)",
        "filter": "status = 'refunded'",
    },
]

_CASE_KEYS = {"id", "question", "llm_reply", "today", "tags", "live", "expect"}
_EXPECT_KEYS = {"status", "status_in", "spec", "rows", "clarification_contains", "warnings_contain"}
_SPEC_KEYS = {"metric", "group_by", "time_grain", "date_column", "date_from", "date_to", "order", "limit"}
_STATUSES = {"answered", "needs_clarification"}
_TAGS = {"routing", "clarification", "safety"}


@dataclass
class Observed:
    status: str  # "answered", "needs_clarification" or "error"
    spec: dict[str, Any] | None = None
    rows: list[dict[str, Any]] | None = None
    warnings: list[str] = field(default_factory=list)
    clarification: str | None = None
    error: str | None = None
    tokens: int = 0
    latency_ms: float = 0.0
    provider: str | None = None


@dataclass
class CaseResult:
    id: str
    passed: bool
    failures: list[str]
    observed_status: str
    status_ok: bool
    spec_fields: dict[str, bool]
    tags: list[str]
    tokens: int = 0
    latency_ms: float = 0.0
    provider: str | None = None


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                case = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"{path.name} line {number}: invalid JSON ({exc})") from None
            problems = validate_case(case)
            if problems:
                raise ValueError(f"{path.name} line {number}: " + "; ".join(problems))
            if case["id"] in seen:
                raise ValueError(f"{path.name} line {number}: duplicate id {case['id']!r}")
            seen.add(case["id"])
            cases.append(case)
    return cases


def validate_case(case: Any) -> list[str]:
    if not isinstance(case, dict):
        return ["case must be an object"]
    problems = []
    unknown = set(case) - _CASE_KEYS
    if unknown:
        problems.append(f"unknown keys {sorted(unknown)}")
    if not isinstance(case.get("id"), str) or not case.get("id"):
        problems.append("id is required")
    question = case.get("question")
    if not isinstance(question, str) or not 3 <= len(question) <= 500:
        problems.append("question must be 3-500 characters")
    if "llm_reply" not in case or not isinstance(case["llm_reply"], (dict, str)):
        problems.append("llm_reply must be an object or a string")
    if not set(case.get("tags", [])) <= _TAGS or not case.get("tags"):
        problems.append(f"tags must be a non-empty subset of {sorted(_TAGS)}")
    expect = case.get("expect")
    if not isinstance(expect, dict):
        problems.append("expect is required")
        return problems
    unknown = set(expect) - _EXPECT_KEYS
    if unknown:
        problems.append(f"unknown expect keys {sorted(unknown)}")
    if ("status" in expect) == ("status_in" in expect):
        problems.append("give exactly one of status / status_in")
    if "status" in expect and expect["status"] not in _STATUSES:
        problems.append("bad status")
    if "status_in" in expect and not (
        isinstance(expect["status_in"], list) and expect["status_in"] and set(expect["status_in"]) <= _STATUSES
    ):
        problems.append("bad status_in")
    spec = expect.get("spec")
    if spec is not None and (not isinstance(spec, dict) or set(spec) - _SPEC_KEYS):
        problems.append(f"spec keys must be within {sorted(_SPEC_KEYS)}")
    if spec is not None and expect.get("status") != "answered":
        problems.append("spec expectations need status 'answered'")
    return problems


def spec_to_dict(spec: Any) -> dict[str, Any]:
    return {
        "metric": spec.metric,
        "group_by": spec.group_by,
        "time_grain": spec.time_grain,
        "date_column": spec.date_column,
        "date_from": spec.date_from.isoformat() if spec.date_from else None,
        "date_to": spec.date_to.isoformat() if spec.date_to else None,
        "order": spec.order,
        "limit": spec.limit,
    }


def _same_value(expected: Any, actual: Any) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(expected) - float(actual)) <= VALUE_TOLERANCE
    return expected == actual


def rows_match(expected: list[dict[str, Any]], actual: list[dict[str, Any]] | None) -> bool:
    if actual is None or len(expected) != len(actual):
        return False
    for want, got in zip(expected, actual):
        if set(want) != set(got):
            return False
        if not all(_same_value(want[key], got[key]) for key in want):
            return False
    return True


def evaluate_case(case: dict[str, Any], observed: Observed, mode: str) -> CaseResult:
    expect = case["expect"]
    failures: list[str] = []

    if observed.status == "error":
        failures.append(f"raised an error: {observed.error}")

    allowed = [expect["status"]] if "status" in expect else expect["status_in"]
    status_ok = observed.status in allowed
    if not status_ok and observed.status != "error":
        failures.append(f"status was {observed.status!r}, expected {' or '.join(allowed)}")

    spec_fields: dict[str, bool] = {}
    for name, wanted in (expect.get("spec") or {}).items():
        actual = (observed.spec or {}).get(name) if observed.spec is not None else "<no spec>"
        spec_fields[name] = observed.spec is not None and actual == wanted
        if not spec_fields[name]:
            failures.append(f"spec.{name} was {actual!r}, expected {wanted!r}")

    if "rows" in expect and not rows_match(expect["rows"], observed.rows):
        failures.append(f"rows were {observed.rows!r}, expected {expect['rows']!r}")

    if mode == "offline" and "clarification_contains" in expect:
        needle = expect["clarification_contains"].lower()
        if needle not in (observed.clarification or "").lower():
            failures.append(f"clarification {observed.clarification!r} does not contain {needle!r}")

    if "warnings_contain" in expect:
        needle = expect["warnings_contain"].lower()
        if not any(needle in warning.lower() for warning in observed.warnings):
            failures.append(f"no warning contains {needle!r} (warnings: {observed.warnings!r})")

    return CaseResult(
        id=case["id"],
        passed=not failures,
        failures=failures,
        observed_status=observed.status,
        status_ok=status_ok,
        spec_fields=spec_fields,
        tags=list(case.get("tags", [])),
        tokens=observed.tokens,
        latency_ms=round(observed.latency_ms, 1),
        provider=observed.provider,
    )


def summarize(results: list[CaseResult], mode: str) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    by_tag: dict[str, dict[str, int]] = {}
    for result in results:
        for tag in result.tags:
            entry = by_tag.setdefault(tag, {"passed": 0, "total": 0})
            entry["total"] += 1
            entry["passed"] += 1 if result.passed else 0

    summary: dict[str, Any] = {
        "mode": mode,
        "cases": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "by_tag": by_tag,
    }

    if mode == "live":
        # Only meaningful against a real model: how often did it route the question correctly?
        fields: dict[str, dict[str, Any]] = {}
        with_spec = [result for result in results if result.spec_fields]
        for result in with_spec:
            for name, ok in result.spec_fields.items():
                entry = fields.setdefault(name, {"correct": 0, "total": 0})
                entry["total"] += 1
                entry["correct"] += 1 if ok else 0
        for entry in fields.values():
            entry["accuracy"] = round(entry["correct"] / entry["total"], 4)
        summary["routing"] = {
            "status_accuracy": round(sum(1 for r in results if r.status_ok) / total, 4) if total else 0.0,
            "full_spec_match": (
                round(sum(1 for r in with_spec if all(r.spec_fields.values())) / len(with_spec), 4)
                if with_spec else None
            ),
            "spec_cases": len(with_spec),
            "field_accuracy": fields,
        }
        summary["latency_ms_avg"] = round(sum(r.latency_ms for r in results) / total, 1) if total else 0.0
        summary["tokens_total"] = sum(r.tokens for r in results)
    return summary