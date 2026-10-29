from datetime import date, datetime
from decimal import Decimal

from domain.query_builder import BuiltQuery
from domain.query_result import ResultInvalid, validate_result

GROUPED = BuiltQuery(sql="x", table_name="t", grouped=True, limit=3)
SINGLE = BuiltQuery(sql="x", table_name="t", grouped=False, limit=3)


def invalid(columns, rows, built):
    try:
        validate_result(columns, rows, built)
    except ResultInvalid as exc:
        return str(exc)
    raise AssertionError("Expected ResultInvalid")


def test_single_value_result():
    result = validate_result(["value"], [(Decimal("500.74"),)], SINGLE)
    assert result.columns == ["value"]
    assert result.rows == [{"value": 500.74}]
    assert result.row_count == 1 and result.truncated is False and result.warnings == []


def test_grouped_result_is_json_safe():
    rows = [
        (datetime(2026, 1, 1), Decimal("10.5")),
        (date(2026, 2, 1), 7),
    ]
    result = validate_result(["group_value", "value"], rows, GROUPED)
    assert result.rows == [
        {"group_value": "2026-01-01T00:00:00", "value": 10.5},
        {"group_value": "2026-02-01", "value": 7},
    ]


def test_truncation_is_detected_and_trimmed():
    rows = [("a", 1), ("b", 2), ("c", 3), ("d", 4)]  # limit 3 + 1 extra row fetched
    result = validate_result(["group_value", "value"], rows, GROUPED)
    assert result.truncated is True
    assert result.row_count == 3
    assert [item["group_value"] for item in result.rows] == ["a", "b", "c"]
    assert any("cut off" in warning for warning in result.warnings)


def test_exactly_at_limit_is_not_truncated():
    rows = [("a", 1), ("b", 2), ("c", 3)]
    result = validate_result(["group_value", "value"], rows, GROUPED)
    assert result.truncated is False and result.warnings == []


def test_empty_result_warns():
    result = validate_result(["group_value", "value"], [], GROUPED)
    assert result.row_count == 0
    assert any("No rows matched" in warning for warning in result.warnings)


def test_all_null_values_warn():
    result = validate_result(["value"], [(None,)], SINGLE)
    assert result.rows == [{"value": None}]
    assert any("empty" in warning for warning in result.warnings)


def test_non_finite_numbers_become_null_with_warning():
    result = validate_result(["group_value", "value"], [("a", float("nan")), ("b", 2.0)], GROUPED)
    assert result.rows[0]["value"] is None
    assert any("not finite" in warning for warning in result.warnings)
    result = validate_result(["value"], [(Decimal("Infinity"),)], SINGLE)
    assert result.rows[0]["value"] is None


def test_unexpected_shapes_are_rejected():
    assert "unexpected shape" in invalid(["a", "b"], [], GROUPED)
    assert "unexpected shape" in invalid(["value"], [], GROUPED)
    assert "unexpected shape" in invalid(["group_value", "value"], [("a",)], GROUPED)


def test_non_numeric_metric_value_is_rejected():
    assert "non-numeric" in invalid(["value"], [("abc",)], SINGLE)
    assert "non-numeric" in invalid(["group_value", "value"], [("a", True)], GROUPED)