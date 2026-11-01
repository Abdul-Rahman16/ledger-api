import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from domain.insight import (
    allowed_numbers,
    build_facts,
    check_explanation,
    extract_numbers,
    fmt_number,
    interpretation_text,
    is_additive,
    period_label,
    template_explanation,
)

SPEC = SimpleNamespace(
    metric="total_revenue",
    group_by="region",
    time_grain=None,
    date_column="order_date",
    date_from=date(2026, 1, 7),
    date_to=date(2026, 1, 9),
    order="value_desc",
    limit=100,
)
CATEGORY_ROWS = [
    {"group_value": "East", "value": 230.25},
    {"group_value": "South", "value": 149.99},
    {"group_value": "North", "value": 120.5},
]
TIME_ROWS = [
    {"group_value": "2026-03-01T00:00:00", "value": 150.0},
    {"group_value": "2026-01-01T00:00:00", "value": 100.0},
    {"group_value": "2026-02-01T00:00:00", "value": 90.5},
]


def category_facts(rows=None, additive=True, truncated=False):
    return build_facts(rows or CATEGORY_ROWS, group_kind="category", time_grain=None,
                       additive=additive, truncated=truncated)


def time_facts(rows=None, grain="month", truncated=False):
    return build_facts(rows or TIME_ROWS, group_kind="time", time_grain=grain,
                       additive=True, truncated=truncated)


def sources_for(facts, rows, question="revenue by region"):
    return [json.dumps(facts.data), json.dumps(rows), question, interpretation_text(SPEC)]


def accepted(text, sources):
    cleaned, problem = check_explanation(text, sources)
    assert problem is None, problem
    return cleaned


def rejected(text, sources):
    cleaned, problem = check_explanation(text, sources)
    assert cleaned is None
    return problem


# ---------- numbers ----------
def test_extract_numbers_handles_formats():
    assert extract_numbers("$1,234.50 and 38% on 2026-01-05.") == [
        Decimal("1234.50"), Decimal("38"), Decimal("2026"), Decimal("01"), Decimal("05"),
    ]
    assert extract_numbers("up 5, down 3.") == [Decimal("5"), Decimal("3")]
    assert extract_numbers("in Q1 of v2") == []
    assert extract_numbers("") == [] and extract_numbers(None) == []


def test_allowed_numbers_include_roundings():
    allowed = allowed_numbers(["value 149.99 and 38.3"])
    assert Decimal("149.99") in allowed and Decimal("150") in allowed and Decimal("150.0") in allowed
    assert Decimal("38") in allowed and Decimal("38.3") in allowed
    assert Decimal("151") not in allowed


def test_fmt_number():
    assert fmt_number(500.74) == "500.74"
    assert fmt_number(120.5) == "120.5"
    assert fmt_number(1000) == "1,000"
    assert fmt_number(0) == "0"
    assert fmt_number(100.0) == "100"
    assert fmt_number(1234567.891) == "1,234,567.89"


def test_is_additive():
    assert is_additive('SUM("amount")') is True
    assert is_additive("COUNT(*)") is True
    assert is_additive('SUM(("amount" * 2))') is True
    assert is_additive('AVG("amount")') is False
    assert is_additive('MAX("amount")') is False
    assert is_additive('COUNT(DISTINCT "order_id")') is False
    assert is_additive('(CAST(SUM("amount") AS DOUBLE PRECISION) / NULLIF(COUNT(*), 0))') is False
    assert is_additive("") is False


def test_period_labels():
    assert period_label("2026-03-01T00:00:00", "month") == "2026-03"
    assert period_label("2026-03-01T00:00:00", None) == "2026-03"
    assert period_label("2026-03-01T00:00:00", "year") == "2026"
    assert period_label("2026-05-01T00:00:00", "quarter") == "2026-Q2"
    assert period_label("2026-03-02T00:00:00", "day") == "2026-03-02"
    assert period_label("2026-03-02T00:00:00", "week") == "2026-03-02"
    assert period_label("garbage", "quarter") == "garbage"


# ---------- facts ----------
def test_single_value_facts():
    facts = build_facts([{"value": 500.74}], group_kind=None, time_grain=None, additive=True, truncated=False)
    assert facts.kind == "single" and facts.data == {"value": 500.74}


def test_empty_and_all_null_facts():
    assert build_facts([], group_kind=None, time_grain=None, additive=True, truncated=False).kind == "empty"
    nulls = [{"value": None}]
    assert build_facts(nulls, group_kind=None, time_grain=None, additive=True, truncated=False).kind == "empty"


def test_category_facts_with_total_and_share():
    facts = category_facts()
    assert facts.kind == "category"
    assert facts.data == {
        "group_count": 3,
        "top_group": "East", "top_value": 230.25,
        "bottom_group": "North", "bottom_value": 120.5,
        "total": 500.74, "top_share_pct": 46.0,
    }


def test_category_facts_without_total_when_not_additive_or_truncated_or_negative():
    assert "total" not in category_facts(additive=False).data
    truncated = category_facts(truncated=True).data
    assert "total" not in truncated and truncated["truncated"] is True
    negative = [{"group_value": "A", "value": 10.0}, {"group_value": "B", "value": -5.0}]
    assert "total" not in category_facts(negative).data


def test_category_ties_and_blank_labels_are_stable():
    rows = [{"group_value": "b", "value": 5.0}, {"group_value": None, "value": 5.0}, {"group_value": "a", "value": 5.0}]
    data = category_facts(rows).data
    assert data["top_group"] == "(blank)" and data["bottom_group"] == "b"


def test_single_group_has_no_bottom_or_share():
    data = category_facts([{"group_value": "East", "value": 230.25}]).data
    assert data == {"group_count": 1, "top_group": "East", "top_value": 230.25}


def test_time_series_facts():
    facts = time_facts()
    assert facts.kind == "time"
    assert facts.data == {
        "period_count": 3,
        "first_period": "2026-01", "first_value": 100.0,
        "last_period": "2026-03", "last_value": 150.0,
        "peak_period": "2026-03", "peak_value": 150.0,
        "low_period": "2026-02", "low_value": 90.5,
        "change_abs": 50.0, "change_pct": 50.0,
    }
    quarter = time_facts(grain="quarter").data
    assert quarter["first_period"] == "2026-Q1"


def test_time_series_zero_start_has_no_percent_change():
    rows = [{"group_value": "2026-01-01T00:00:00", "value": 0.0}, {"group_value": "2026-02-01T00:00:00", "value": 5.0}]
    data = time_facts(rows).data
    assert "change_pct" not in data and data["change_abs"] == 5.0


def test_null_values_are_skipped_in_facts():
    rows = CATEGORY_ROWS + [{"group_value": "West", "value": None}]
    assert category_facts(rows).data["group_count"] == 3


# ---------- grounding ----------
def test_grounded_explanations_are_accepted():
    facts = category_facts()
    sources = sources_for(facts, CATEGORY_ROWS)
    text = ("Total revenue from 2026-01-07 to 2026-01-09 is highest for East at 230.25 and lowest "
            "for North at 120.5. East makes up 46% of the 500.74 total.")
    assert accepted(text, sources) == text


def test_rounding_and_thousands_separators_are_allowed():
    sources = ["value 1234.5 and 149.99 and 38.3"]
    accepted("Revenue was 1,234.50, about 150 overall, and 38% for the top group.", sources)
    accepted("Revenue was $1,234.5 in total for the period shown.", sources)


def test_ungrounded_numbers_are_rejected():
    sources = sources_for(category_facts(), CATEGORY_ROWS)
    assert "ungrounded" in rejected("East is highest at 999.99 across the groups shown.", sources)
    assert "ungrounded" in rejected("Revenue grew 73.2% compared with last year overall.", sources)


def test_abbreviated_ordinal_and_spelled_out_numbers_are_rejected():
    sources = sources_for(category_facts(), CATEGORY_ROWS)
    assert "abbreviated" in rejected("East brought in 230K of the revenue this period.", sources)
    assert "abbreviated" in rejected("East brought in 0.23 million of revenue this period.", sources)
    assert "abbreviated" in rejected("East was the 1st region by revenue in this period.", sources)
    assert "spelled-out" in rejected("There are three regions and East leads them all.", sources)
    assert "spelled-out" in rejected("East revenue is almost double the North revenue.", sources)


def test_markup_links_and_length_are_rejected():
    sources = sources_for(category_facts(), CATEGORY_ROWS)
    for text in ("East is **highest** at 230.25 this period.",
                 "East is highest <b>230.25</b> this period.",
                 "East is highest at 230.25, see https://evil.example now",
                 "East is highest at `230.25` this period.",
                 "[East](http://x) is highest at 230.25 this period"):
        assert "markup" in rejected(text, sources)
    assert rejected("Too short", sources) == "too short"
    assert rejected("East " * 200, sources) == "too long"
    assert rejected(None, sources) == "too short"


def test_control_characters_and_whitespace_are_cleaned():
    sources = sources_for(category_facts(), CATEGORY_ROWS)
    assert accepted("East  is\nhighest\x00 at 230.25   overall.", sources) == "East is highest at 230.25 overall."


def test_dates_from_the_interpretation_are_grounded():
    sources = sources_for(category_facts(), CATEGORY_ROWS)
    accepted("For 2026-01-07 to 2026-01-09, East is highest at 230.25 in the data.", sources)


# ---------- template ----------
def test_template_text_is_exact_for_a_category_result():
    text = template_explanation(category_facts(), metric_label="total revenue", spec=SPEC)
    assert text == (
        "Total revenue from 2026-01-07 to 2026-01-09 is highest for East at 230.25 and lowest for North "
        "at 120.5, across 3 groups. Together they total 500.74, and East makes up 46% of that."
    )


def test_template_text_for_single_and_empty_results():
    single = build_facts([{"value": 500.74}], group_kind=None, time_grain=None, additive=True, truncated=False)
    bare = SimpleNamespace(date_from=None, date_to=None)
    assert template_explanation(single, metric_label="total revenue", spec=bare) == "Total revenue is 500.74."
    since = SimpleNamespace(date_from=date(2026, 1, 1), date_to=None)
    assert template_explanation(single, metric_label="orders", spec=since) == "Orders since 2026-01-01 is 500.74."
    empty = build_facts([], group_kind=None, time_grain=None, additive=True, truncated=False)
    assert template_explanation(empty, metric_label="x", spec=bare).startswith("No data matched this question.")
    one = category_facts([{"group_value": "East", "value": 230.25}])
    assert template_explanation(one, metric_label="revenue", spec=bare) == "Revenue is 230.25 for East."


def test_template_text_for_a_time_series():
    bare = SimpleNamespace(date_from=None, date_to=None)
    text = template_explanation(time_facts(), metric_label="total revenue", spec=bare)
    assert text == ("Total revenue went from 100 in 2026-01 to 150 in 2026-03, a change of +50.0%. "
                    "The peak was 150 in 2026-03.")
    one = time_facts([{"group_value": "2026-01-01T00:00:00", "value": 100.0}])
    assert template_explanation(one, metric_label="total revenue", spec=bare) == "Total revenue was 100 in 2026-01."


def test_every_template_passes_its_own_grounding_check():
    cases = [
        (category_facts(), CATEGORY_ROWS),
        (category_facts(additive=False), CATEGORY_ROWS),
        (category_facts([{"group_value": "East", "value": 230.25}]), [{"group_value": "East", "value": 230.25}]),
        (time_facts(), TIME_ROWS),
        (time_facts(grain="quarter"), TIME_ROWS),
        (time_facts([{"group_value": "2026-01-01T00:00:00", "value": 100.0}]), TIME_ROWS[:1]),
        (build_facts([{"value": 1234567.891}], group_kind=None, time_grain=None, additive=True, truncated=False),
         [{"value": 1234567.891}]),
    ]
    for facts, rows in cases:
        text = template_explanation(facts, metric_label="total revenue", spec=SPEC)
        accepted(text, sources_for(facts, rows))