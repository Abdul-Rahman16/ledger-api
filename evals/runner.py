"""
Eval runner. Needs a real Postgres (the same one the API uses).

It ingests the fixture CSV as a throwaway dataset, defines the fixture metrics through the
real metric service, replays every golden case through ask_service.ask_question, scores the
results and removes the dataset again.

  offline  the model's reply is replayed from the golden file: deterministic, no network (used in CI)
  live     the real Groq/Gemini models answer: measures routing accuracy, tokens and latency
"""

import json
import time
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select, text

from core.config import settings
from core.db import SessionLocal
from core.llm import complete_json
from core.llm_types import LLMReply, LLMUnavailable
from domain import ask_service, dataset_service, metric_service
from domain.ingestion import ingest_dataset
from domain.models import Dataset, DatasetColumn, MetricDefinition, QueryLog
from domain.query_builder import TABLE_RE, QueryRejected, assert_safe_sql
from domain.query_executor import QueryExecutionError
from domain.query_result import ResultInvalid
from evals import golden


def scripted_llm(reply: Any):
    """Replays a recorded model reply (an object, or a raw string for malformed-output cases)."""

    def llm(system: str, user: str) -> LLMReply:
        body = reply if isinstance(reply, str) else json.dumps(reply)
        return LLMReply(text=body, provider="scripted", model="scripted", tokens=0)

    return llm


def observe(outcome) -> golden.Observed:
    query = outcome.query
    return golden.Observed(
        status=outcome.status,
        spec=golden.spec_to_dict(outcome.spec) if outcome.spec is not None else None,
        rows=query.rows if query is not None else None,
        warnings=list(query.warnings) if query is not None else [],
        clarification=outcome.clarification,
        tokens=outcome.tokens_used,
        provider=outcome.provider,
    )


def run_case(db, dataset, case: dict[str, Any], mode: str) -> golden.CaseResult:
    today = date.fromisoformat(case["today"]) if "today" in case else golden.DEFAULT_TODAY
    llm = scripted_llm(case["llm_reply"]) if mode == "offline" else complete_json
    started = time.perf_counter()
    try:
        outcome = ask_service.ask_question(
            db, dataset, None, case["question"], explain=False, today=today, llm=llm
        )
        observed = observe(outcome)
    except (QueryRejected, LLMUnavailable, QueryExecutionError, ResultInvalid) as exc:
        db.rollback()
        observed = golden.Observed(status="error", error=f"{type(exc).__name__}: {exc}")
    observed.latency_ms = (time.perf_counter() - started) * 1000
    return golden.evaluate_case(case, observed, mode)


def check_invariants(db, dataset_id, table_name: str, column_names: list[str], datasets_before: int) -> list[str]:
    """Checks that hold for every case, whatever the model said."""
    problems: list[str] = []
    allowed = {table_name, "group_value", "value", *column_names}
    logged = db.execute(
        select(QueryLog.generated_sql).where(
            QueryLog.dataset_id == dataset_id, QueryLog.generated_sql.is_not(None)
        )
    ).scalars().all()
    for sql in logged:
        try:
            assert_safe_sql(sql, allowed)
        except QueryRejected as exc:
            problems.append(f"a logged query failed the SQL safety gate: {exc}")
    datasets_now = db.scalar(select(func.count()).select_from(Dataset))
    if datasets_now != datasets_before + 1:
        problems.append(f"the datasets table has {datasets_now} rows, expected {datasets_before + 1}")
    return problems


def cleanup(db, dataset_id, table_name: str | None) -> None:
    db.rollback()
    db.execute(delete(QueryLog).where(QueryLog.dataset_id == dataset_id))
    db.execute(delete(MetricDefinition).where(MetricDefinition.dataset_id == dataset_id))
    db.execute(delete(DatasetColumn).where(DatasetColumn.dataset_id == dataset_id))
    db.execute(delete(Dataset).where(Dataset.id == dataset_id))
    if table_name and TABLE_RE.match(table_name):
        db.execute(text(f'DROP TABLE IF EXISTS "{table_name}"'))
    db.commit()


def run_eval(
    mode: str = "offline",
    *,
    only: set[str] | None = None,
    delay: float = 0.0,
    cases_path: Path = golden.CASES_PATH,
) -> dict[str, Any]:
    if mode not in ("offline", "live"):
        raise ValueError("mode must be 'offline' or 'live'")
    if mode == "live" and not (settings.groq_api_key or settings.gemini_api_key):
        raise RuntimeError("Live mode needs GROQ_API_KEY or GEMINI_API_KEY in .env")

    cases = golden.load_cases(cases_path)
    if mode == "live":
        cases = [case for case in cases if case["live"]]
    if only:
        cases = [case for case in cases if case["id"] in only]
    if not cases:
        raise RuntimeError("No cases selected.")

    db = SessionLocal()
    dataset_id = None
    table_name = None
    try:
        datasets_before = db.scalar(select(func.count()).select_from(Dataset))
        dataset = ingest_dataset(db, golden.CSV_PATH.name, golden.CSV_PATH.read_bytes(), user_id=None)
        dataset_id, table_name = dataset.id, dataset.table_name
        for metric in golden.FIXTURE_METRICS:
            metric_service.create_metric(
                db, dataset, metric["name"], metric["description"], metric["expression"], metric["filter"]
            )
        column_names = [column.name for column in dataset_service.get_columns(db, dataset_id)]

        results = []
        for index, case in enumerate(cases):
            if mode == "live" and index and delay:
                time.sleep(delay)
            results.append(run_case(db, dataset, case, mode))

        invariant_problems = check_invariants(db, dataset_id, table_name, column_names, datasets_before)
    finally:
        if dataset_id is not None:
            cleanup(db, dataset_id, table_name)
        db.close()

    return {
        "meta": {
            "mode": mode,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "models": (
                {"groq": settings.groq_model if settings.groq_api_key else None,
                 "gemini": settings.gemini_model if settings.gemini_api_key else None}
                if mode == "live" else None
            ),
            "fixture_rows": 32,
        },
        "summary": golden.summarize(results, mode),
        "invariant_problems": invariant_problems,
        "cases": [asdict(result) for result in results],
    }


def write_report(report: dict[str, Any], path: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")