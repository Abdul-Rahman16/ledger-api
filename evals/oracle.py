"""
Independent reference implementation (pure Python, no database, no SQL).

It recomputes metric results straight from the fixture CSV so the expected values in
golden_cases.jsonl can be checked against something other than the SQL pipeline.
"""

import csv
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).parent / "fixtures"
CSV_PATH = FIXTURE_DIR / "orders_eval.csv"

# metric name -> (aggregate, status the metric filters on)
METRIC_RULES = {
    "total_revenue": ("sum", "completed"),
    "order_count": ("count", "completed"),
    "avg_order_value": ("avg", "completed"),
    "refunded_amount": ("sum", "refunded"),
}
CATEGORY_COLUMNS = {"region", "product", "status"}


def load_rows(path: Path = CSV_PATH) -> list[dict[str, Any]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return [
            {
                "order_id": int(row["order_id"]),
                "region": row["region"],
                "product": row["product"],
                "amount": float(row["amount"]),
                "order_date": date.fromisoformat(row["order_date"]),
                "status": row["status"],
            }
            for row in csv.DictReader(handle)
        ]


def _bucket(day: date, grain: str) -> str:
    if grain == "year":
        start = date(day.year, 1, 1)
    elif grain == "quarter":
        start = date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)
    elif grain == "week":
        start = day - timedelta(days=day.weekday())
    elif grain == "day":
        start = day
    else:
        start = date(day.year, day.month, 1)
    return datetime(start.year, start.month, start.day).isoformat()


def _aggregate(kind: str, rows: list[dict[str, Any]]):
    if kind == "count":
        return len(rows)
    if not rows:
        return None
    total = sum(row["amount"] for row in rows)
    value = total if kind == "sum" else total / len({row["order_id"] for row in rows})
    return round(value, 2)


def compute(
    metric: str,
    *,
    group_by: str | None = None,
    time_grain: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    order: str | None = None,
    limit: int = 100,
    rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    kind, status = METRIC_RULES[metric]
    data = [
        row for row in (rows if rows is not None else load_rows())
        if row["status"] == status
        and (date_from is None or row["order_date"] >= date_from)
        and (date_to is None or row["order_date"] <= date_to)
    ]
    if group_by is None:
        return [{"value": _aggregate(kind, data)}]

    is_time = group_by == "order_date"
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in data:
        key = _bucket(row["order_date"], time_grain or "month") if is_time else row[group_by]
        groups.setdefault(key, []).append(row)
    result = [{"group_value": key, "value": _aggregate(kind, members)} for key, members in groups.items()]

    order = order or ("group_asc" if is_time else "value_desc")
    if order == "value_desc":
        result.sort(key=lambda item: (-item["value"], item["group_value"]))
    elif order == "value_asc":
        result.sort(key=lambda item: (item["value"], item["group_value"]))
    elif order == "group_asc":
        result.sort(key=lambda item: item["group_value"])
    else:
        result.sort(key=lambda item: item["group_value"], reverse=True)
    return result[:limit]