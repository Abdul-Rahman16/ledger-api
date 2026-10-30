"""
Grounded insights (pure Python, no I/O).

The server computes the facts about a result. A language model may phrase them,
but every number in its explanation must come from the facts / rows it was shown.
If it cites anything else, the explanation is replaced by a deterministic template
built from the same facts. This module holds the fact builder, the grounding check
and the template.
"""

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Sequence

MAX_EXPLANATION_CHARS = 600
MIN_EXPLANATION_CHARS = 10
MAX_PROMPT_ROWS = 20
MAX_LABEL_CHARS = 60

_NUMBER = re.compile(r"(?<!\w)\d[\d,]*(?:\.\d+)?(?!\w)")
_SUFFIXED = re.compile(
    r"\d\s?(?:k|m|b|bn|mm|lakhs?|crores?|million|billion|thousand|st|nd|rd|th)\b", re.IGNORECASE
)
_NUMBER_WORDS = re.compile(
    r"\b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty"
    r"|hundred|thousand|million|billion|half|double|doubled|triple|tripled)\b",
    re.IGNORECASE,
)
_FORBIDDEN = re.compile(r"[<>`*]|https?:|www\.|\]\(", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class Facts:
    kind: str  # "empty", "single", "category" or "time"
    data: dict[str, Any]


# ---------- small helpers ----------
def _num(value: Any) -> float:
    return round(float(value), 2)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value


def label_text(value: Any) -> str:
    if value is None:
        return "(blank)"
    return " ".join(_CONTROL.sub(" ", str(value)).split())[:MAX_LABEL_CHARS] or "(blank)"


def period_label(raw: Any, grain: str | None) -> str:
    text = str(raw)
    if grain == "year":
        return text[:4]
    if grain == "quarter":
        try:
            year, month = int(text[:4]), int(text[5:7])
        except ValueError:
            return text[:10]
        return f"{year}-Q{(month - 1) // 3 + 1}"
    if grain in ("day", "week"):
        return text[:10]
    return text[:7]  # month


def fmt_number(value: Any) -> str:
    text = f"{round(float(value), 2):,.2f}"
    return text.rstrip("0").rstrip(".")


def is_additive(sql_expression: str) -> bool:
    """True when summing the per-group values gives the overall value (plain SUM / COUNT)."""
    upper = (sql_expression or "").upper()
    if any(token in upper for token in ("AVG(", "MIN(", "MAX(", "DISTINCT", "NULLIF")):
        return False  # NULLIF marks a ratio
    return "SUM(" in upper or "COUNT(" in upper


# ---------- facts ----------
def build_facts(
    rows: Sequence[dict[str, Any]],
    *,
    group_kind: str | None,
    time_grain: str | None,
    additive: bool,
    truncated: bool,
) -> Facts:
    valid = [row for row in rows if _is_number(row.get("value"))]
    if not valid:
        return Facts("empty", {"row_count": len(rows)})

    if group_kind is None:
        return Facts("single", {"value": _num(valid[0]["value"])})

    if group_kind == "time":
        ordered = sorted(valid, key=lambda row: str(row["group_value"]))
        first, last = ordered[0], ordered[-1]
        peak = max(ordered, key=lambda row: row["value"])
        low = min(ordered, key=lambda row: row["value"])
        data: dict[str, Any] = {
            "period_count": len(ordered),
            "first_period": period_label(first["group_value"], time_grain),
            "first_value": _num(first["value"]),
            "last_period": period_label(last["group_value"], time_grain),
            "last_value": _num(last["value"]),
            "peak_period": period_label(peak["group_value"], time_grain),
            "peak_value": _num(peak["value"]),
            "low_period": period_label(low["group_value"], time_grain),
            "low_value": _num(low["value"]),
        }
        if len(ordered) > 1:
            data["change_abs"] = _num(last["value"] - first["value"])
            if first["value"] != 0:
                data["change_pct"] = round((last["value"] - first["value"]) / abs(first["value"]) * 100, 1)
        if truncated:
            data["truncated"] = True
        return Facts("time", data)

    ordered = sorted(valid, key=lambda row: (-row["value"], label_text(row["group_value"])))
    top, bottom = ordered[0], ordered[-1]
    data = {
        "group_count": len(ordered),
        "top_group": label_text(top["group_value"]),
        "top_value": _num(top["value"]),
    }
    if len(ordered) > 1:
        data["bottom_group"] = label_text(bottom["group_value"])
        data["bottom_value"] = _num(bottom["value"])
    if truncated:
        data["truncated"] = True
    else:
        values = [row["value"] for row in ordered]
        total = sum(values)
        if additive and len(ordered) > 1 and all(value >= 0 for value in values) and total > 0:
            data["total"] = _num(total)
            data["top_share_pct"] = round(top["value"] / total * 100, 1)
    return Facts("category", data)


def interpretation_text(spec: Any) -> str:
    """How the question was understood, as compact JSON (shown to the model and used for grounding)."""
    fields = {
        "metric": spec.metric,
        "group_by": spec.group_by,
        "time_grain": spec.time_grain,
        "date_column": spec.date_column,
        "date_from": spec.date_from.isoformat() if spec.date_from else None,
        "date_to": spec.date_to.isoformat() if spec.date_to else None,
        "order": spec.order,
        "limit": spec.limit,
    }
    return json.dumps({key: value for key, value in fields.items() if value is not None})


# ---------- grounding ----------
def extract_numbers(text: str) -> list[Decimal]:
    numbers: list[Decimal] = []
    for token in _NUMBER.findall(text or ""):
        try:
            numbers.append(Decimal(token.replace(",", "")))
        except InvalidOperation:
            continue
    return numbers


def allowed_numbers(source_texts: Iterable[str]) -> set[Decimal]:
    """Every number in the sources, plus its roundings to 0, 1 and 2 decimals."""
    allowed: set[Decimal] = set()
    for text in source_texts:
        for number in extract_numbers(text):
            allowed.add(number)
            for places in (0, 1, 2):
                allowed.add(round(number, places))
    return allowed


def check_explanation(text: str | None, source_texts: Iterable[str]) -> tuple[str | None, str | None]:
    """Returns (cleaned_text, None) when the explanation is acceptable, else (None, reason)."""
    cleaned = " ".join(_CONTROL.sub(" ", text or "").split())
    if len(cleaned) < MIN_EXPLANATION_CHARS:
        return None, "too short"
    if len(cleaned) > MAX_EXPLANATION_CHARS:
        return None, "too long"
    if _FORBIDDEN.search(cleaned):
        return None, "contains markup or links"
    if _SUFFIXED.search(cleaned):
        return None, "abbreviated or ordinal number"
    if _NUMBER_WORDS.search(cleaned):
        return None, "spelled-out number"
    allowed = allowed_numbers(list(source_texts))
    unknown = [number for number in extract_numbers(cleaned) if number not in allowed]
    if unknown:
        return None, "ungrounded numbers: " + ", ".join(str(number) for number in unknown[:5])
    return cleaned, None


# ---------- deterministic template ----------
def _period_phrase(spec: Any) -> str:
    date_from, date_to = getattr(spec, "date_from", None), getattr(spec, "date_to", None)
    if date_from and date_to:
        return f" from {date_from.isoformat()} to {date_to.isoformat()}"
    if date_from:
        return f" since {date_from.isoformat()}"
    if date_to:
        return f" up to {date_to.isoformat()}"
    return ""


def template_explanation(facts: Facts, *, metric_label: str, spec: Any) -> str:
    label = metric_label[:1].upper() + metric_label[1:]
    period = _period_phrase(spec)
    data = facts.data

    if facts.kind == "empty":
        return f"No data matched this question{period}. Check the date range and the metric's filter."

    if facts.kind == "single":
        return f"{label}{period} is {fmt_number(data['value'])}."

    if facts.kind == "category":
        if data["group_count"] == 1:
            return f"{label}{period} is {fmt_number(data['top_value'])} for {data['top_group']}."
        text = (
            f"{label}{period} is highest for {data['top_group']} at {fmt_number(data['top_value'])} "
            f"and lowest for {data['bottom_group']} at {fmt_number(data['bottom_value'])}, "
            f"across {data['group_count']} groups."
        )
        if "total" in data:
            text += (
                f" Together they total {fmt_number(data['total'])}, and {data['top_group']} "
                f"makes up {fmt_number(data['top_share_pct'])}% of that."
            )
        return text

    # time series
    if data["period_count"] == 1:
        return f"{label}{period} was {fmt_number(data['first_value'])} in {data['first_period']}."
    text = (
        f"{label}{period} went from {fmt_number(data['first_value'])} in {data['first_period']} "
        f"to {fmt_number(data['last_value'])} in {data['last_period']}"
    )
    if "change_pct" in data:
        text += f", a change of {data['change_pct']:+.1f}%"
    text += f". The peak was {fmt_number(data['peak_value'])} in {data['peak_period']}."
    return text