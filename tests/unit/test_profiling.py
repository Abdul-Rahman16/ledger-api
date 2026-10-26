import pandas as pd

from domain.profiling import (
    clean_dataframe,
    normalize_columns,
    profile_dataframe,
    quality_score,
)


def test_normalize_columns_handles_spaces_case_duplicates_and_digits():
    result = normalize_columns(["Order Total", "order_total", "2024 Sales", "  "])
    assert result == ["order_total", "order_total_2", "c_2024_sales", "column"]


def test_clean_dataframe_drops_empty_rows_columns_and_duplicates():
    df = pd.DataFrame(
        {"A": [1, 1, None, 2], "B": [" x ", " x ", None, "y"], "Empty": [None] * 4}
    )
    cleaned, report = clean_dataframe(df)
    assert list(cleaned.columns) == ["a", "b"]
    assert report == {
        "original_rows": 4,
        "empty_rows_removed": 1,
        "duplicate_rows_removed": 1,
        "final_rows": 2,
    }


def test_type_inference_converts_only_fully_parseable_columns():
    df = pd.DataFrame(
        {
            "n": ["1", "2", "3"],
            "d": ["2024-01-05", "2024-02-10", "2024-03-15"],
            "t": ["a", "b", "c"],
            "b": ["true", "false", "true"],
            "mixed": ["1", "2", "oops"],
        }
    )
    cleaned, _ = clean_dataframe(df)
    dtypes = {p["name"]: p["dtype"] for p in profile_dataframe(cleaned)}
    assert dtypes == {
        "n": "integer",
        "d": "datetime",
        "t": "text",
        "b": "boolean",
        "mixed": "text",  # one bad value keeps the column as text, nothing is lost
    }


def test_month_names_are_not_misread_as_dates():
    cleaned, _ = clean_dataframe(pd.DataFrame({"m": ["May", "June", "July"]}))
    assert profile_dataframe(cleaned)[0]["dtype"] == "text"


def test_profile_reports_nulls_uniques_and_numeric_stats():
    profile = profile_dataframe(pd.DataFrame({"x": [1.0, 2.0, 3.0, None]}))[0]
    assert profile["dtype"] == "float"
    assert profile["null_pct"] == 25.0
    assert profile["unique_count"] == 3
    assert profile["stats"] == {"min": 1.0, "max": 3.0, "mean": 2.0}


def test_quality_score_penalises_nulls_and_duplicates():
    assert quality_score([{"null_pct": 0.0}], 0, 10) == 100.0
    assert quality_score([{"null_pct": 10.0}], 2, 10) == 70.0
    assert quality_score([], 0, 0) == 0.0