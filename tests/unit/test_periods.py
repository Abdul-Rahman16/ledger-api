from datetime import date

from domain.periods import PeriodError, resolve_period

TODAY = date(2026, 10, 29)


def r(period, today=TODAY):
    return resolve_period(period, today)


def bad(period):
    try:
        resolve_period(period, TODAY)
    except PeriodError:
        return
    raise AssertionError(f"Expected PeriodError for {period!r}")


def test_relative_day_periods():
    assert r("today") == (date(2026, 10, 29), date(2026, 10, 29))
    assert r("yesterday") == (date(2026, 10, 28), date(2026, 10, 28))
    assert r("last_7_days") == (date(2026, 10, 23), date(2026, 10, 29))
    assert r("last_30_days") == (date(2026, 9, 30), date(2026, 10, 29))


def test_relative_month_quarter_year_periods():
    assert r("this_month") == (date(2026, 10, 1), date(2026, 10, 31))
    assert r("last_month") == (date(2026, 9, 1), date(2026, 9, 30))
    assert r("this_quarter") == (date(2026, 10, 1), date(2026, 12, 31))
    assert r("last_quarter") == (date(2026, 7, 1), date(2026, 9, 30))
    assert r("this_year") == (date(2026, 1, 1), date(2026, 12, 31))
    assert r("last_year") == (date(2025, 1, 1), date(2025, 12, 31))


def test_year_boundaries():
    jan = date(2026, 1, 15)
    assert r("last_month", jan) == (date(2025, 12, 1), date(2025, 12, 31))
    assert r("last_quarter", jan) == (date(2025, 10, 1), date(2025, 12, 31))
    assert r("last_30_days", jan) == (date(2025, 12, 17), date(2026, 1, 15))


def test_all_time_means_no_filter():
    assert r("all_time") == (None, None)


def test_absolute_periods():
    assert r("2026") == (date(2026, 1, 1), date(2026, 12, 31))
    assert r("2026-Q1") == (date(2026, 1, 1), date(2026, 3, 31))
    assert r("2026-q4") == (date(2026, 10, 1), date(2026, 12, 31))
    assert r("2026-01") == (date(2026, 1, 1), date(2026, 1, 31))
    assert r("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
    assert r("2028-02") == (date(2028, 2, 1), date(2028, 2, 29))  # leap year


def test_case_and_whitespace_are_tolerated():
    assert r("  LAST_MONTH ") == (date(2026, 9, 1), date(2026, 9, 30))


def test_unknown_or_invalid_periods_are_rejected():
    for period in ("", "   ", "next_year", "2026-13", "2026-00", "2026-Q5", "2026-Q0", "abc",
                   "1800", "3000", "2026-1", "last month", "2026-01-05", "'; DROP TABLE x"):
        bad(period)