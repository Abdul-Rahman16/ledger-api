"""Validation and JSON-safe conversion of a query result (pure Python, no DB)."""

import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Sequence

from domain.query_builder import GROUP_ALIAS, VALUE_ALIAS, BuiltQuery


class ResultInvalid(Exception):
    """The database returned something the platform will not pass on."""


@dataclass(frozen=True)
class ValidatedResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    warnings: list[str]


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Decimal):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def validate_result(
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    built: BuiltQuery,
) -> ValidatedResult:
    expected = [GROUP_ALIAS, VALUE_ALIAS] if built.grouped else [VALUE_ALIAS]
    if list(columns) != expected:
        raise ResultInvalid("The result had an unexpected shape.")
    if any(len(row) != len(expected) for row in rows):
        raise ResultInvalid("The result had an unexpected shape.")

    warnings: list[str] = []
    truncated = len(rows) > built.limit
    if truncated:
        rows = rows[: built.limit]
        warnings.append(f"Results were cut off at {built.limit} rows. Narrow the date range or lower the limit.")

    value_index = len(expected) - 1
    non_finite = False
    cleaned: list[dict[str, Any]] = []
    for row in rows:
        raw_value = row[value_index]
        if raw_value is not None and not _is_number(raw_value):
            raise ResultInvalid("The metric returned a non-numeric value.")
        if isinstance(raw_value, float) and not math.isfinite(raw_value):
            non_finite = True
        elif isinstance(raw_value, Decimal) and not raw_value.is_finite():
            non_finite = True
        cleaned.append({name: _json_safe(value) for name, value in zip(expected, row)})

    if non_finite:
        warnings.append("Some values were not finite numbers and were returned as null.")
    if not cleaned:
        warnings.append("No rows matched. Check the date range and the metric's filter.")
    elif all(item[VALUE_ALIAS] is None for item in cleaned):
        warnings.append(
            "The metric is empty for every row (no matching data, or a division by zero)."
        )

    return ValidatedResult(
        columns=expected,
        rows=cleaned,
        row_count=len(cleaned),
        truncated=truncated,
        warnings=warnings,
    )