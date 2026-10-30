"""
Deterministic date-period resolution.

The language model never does date arithmetic. It names a period ("last_month",
"2026-Q1", "2026-01") and the server turns it into an inclusive date range.
"""

import calendar
import re
from datetime import date, timedelta

RELATIVE_PERIODS = (
    "today",
    "yesterday",
    "last_7_days",
    "last_30_days",
    "this_month",
    "last_month",
    "this_quarter",
    "last_quarter",
    "this_year",
    "last_year",
    "all_time",
)
MIN_YEAR = 1990
MAX_YEAR = 2100

_YEAR = re.compile(r"^(\d{4})$")
_QUARTER = re.compile(r"^(\d{4})-q([1-4])$")
_MONTH = re.compile(r"^(\d{4})-(\d{2})$")


class PeriodError(ValueError):
    """The period string is not one the platform understands."""


def _check_year(year: int) -> int:
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise PeriodError(f"Year {year} is out of range.")
    return year


def _month_range(year: int, month: int) -> tuple[date, date]:
    _check_year(year)
    if not 1 <= month <= 12:
        raise PeriodError(f"Month {month} is out of range.")
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _quarter_range(year: int, quarter: int) -> tuple[date, date]:
    first_month = 3 * (quarter - 1) + 1
    start, _ = _month_range(year, first_month)
    _, end = _month_range(year, first_month + 2)
    return start, end


def resolve_period(period: str, today: date) -> tuple[date | None, date | None]:
    """Returns an inclusive (date_from, date_to). (None, None) means no date filter."""
    p = (period or "").strip().lower()
    if not p:
        raise PeriodError("Empty period.")

    if p == "all_time":
        return None, None
    if p == "today":
        return today, today
    if p == "yesterday":
        day = today - timedelta(days=1)
        return day, day
    if p == "last_7_days":
        return today - timedelta(days=6), today
    if p == "last_30_days":
        return today - timedelta(days=29), today
    if p == "this_month":
        return _month_range(today.year, today.month)
    if p == "last_month":
        last_day_prev = today.replace(day=1) - timedelta(days=1)
        return _month_range(last_day_prev.year, last_day_prev.month)

    current_quarter = (today.month - 1) // 3 + 1
    if p == "this_quarter":
        return _quarter_range(today.year, current_quarter)
    if p == "last_quarter":
        if current_quarter == 1:
            return _quarter_range(today.year - 1, 4)
        return _quarter_range(today.year, current_quarter - 1)
    if p == "this_year":
        return date(_check_year(today.year), 1, 1), date(today.year, 12, 31)
    if p == "last_year":
        year = _check_year(today.year - 1)
        return date(year, 1, 1), date(year, 12, 31)

    match = _MONTH.match(p)
    if match:
        return _month_range(int(match.group(1)), int(match.group(2)))
    match = _QUARTER.match(p)
    if match:
        return _quarter_range(int(match.group(1)), int(match.group(2)))
    match = _YEAR.match(p)
    if match:
        year = _check_year(int(match.group(1)))
        return date(year, 1, 1), date(year, 12, 31)

    raise PeriodError(f"Unknown period '{p[:30]}'.")