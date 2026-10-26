import json
import re

import numpy as np
import pandas as pd

MAX_TOP_VALUES = 5
MAX_COLUMN_NAME_LENGTH = 60


def normalize_column_name(name) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", str(name).strip()).strip("_").lower()
    cleaned = cleaned[:MAX_COLUMN_NAME_LENGTH]
    if not cleaned:
        cleaned = "column"
    if cleaned[0].isdigit():
        cleaned = f"c_{cleaned}"
    return cleaned


def normalize_columns(columns) -> list[str]:
    seen: dict[str, int] = {}
    result = []
    for col in columns:
        base = normalize_column_name(col)
        seen[base] = seen.get(base, 0) + 1
        result.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return result


def _is_text_like(series: pd.Series) -> bool:
    return series.dtype == object or pd.api.types.is_string_dtype(series)


def _clean_cell(value):
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True)
    return value


def _infer_types(df: pd.DataFrame) -> pd.DataFrame:
    """Convert a text column only when EVERY non-null value parses, so no
    value is ever silently turned into null by type inference."""
    for col in df.columns:
        series = df[col]
        if not _is_text_like(series):
            continue
        non_null = series.dropna()
        if non_null.empty:
            continue
        as_text = non_null.astype(str)

        if as_text.str.lower().isin(["true", "false"]).all():
            df[col] = series.map(lambda v: None if pd.isna(v) else str(v).lower() == "true")
            continue

        if pd.to_numeric(non_null, errors="coerce").notna().all():
            df[col] = pd.to_numeric(series)
            continue

        # Require a digit in every value so words like "May" are not read as dates.
        if as_text.str.contains(r"\d").all():
            parsed = pd.to_datetime(non_null, errors="coerce", format="mixed")
            if parsed.notna().all():
                df[col] = pd.to_datetime(series, format="mixed")
    return df


def clean_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    original_rows = len(df)
    df = df.copy()
    df.columns = normalize_columns(df.columns)

    for col in df.columns:
        if _is_text_like(df[col]):
            df[col] = df[col].map(_clean_cell)

    df = df.dropna(axis=1, how="all")
    df = df.dropna(axis=0, how="all")
    rows_after_empty = len(df)
    df = df.drop_duplicates().reset_index(drop=True)
    df = _infer_types(df)

    report = {
        "original_rows": original_rows,
        "empty_rows_removed": original_rows - rows_after_empty,
        "duplicate_rows_removed": rows_after_empty - len(df),
        "final_rows": len(df),
    }
    return df, report


def _dtype_label(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_integer_dtype(series):
        return "integer"
    if pd.api.types.is_float_dtype(series):
        return "float"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    return "text"


def _column_stats(series: pd.Series, label: str) -> dict:
    non_null = series.dropna()
    if non_null.empty:
        return {}
    if label in ("integer", "float"):
        finite = non_null[np.isfinite(non_null.astype(float))]
        if finite.empty:
            return {}
        return {
            "min": float(finite.min()),
            "max": float(finite.max()),
            "mean": round(float(finite.mean()), 4),
        }
    if label == "datetime":
        return {"min": non_null.min().isoformat(), "max": non_null.max().isoformat()}
    top = non_null.astype(str).value_counts().head(MAX_TOP_VALUES)
    return {"top_values": [{"value": str(k), "count": int(v)} for k, v in top.items()]}


def profile_dataframe(df: pd.DataFrame) -> list[dict]:
    profiles = []
    for position, col in enumerate(df.columns):
        series = df[col]
        label = _dtype_label(series)
        profiles.append(
            {
                "name": col,
                "position": position,
                "dtype": label,
                "null_pct": round(float(series.isna().mean()) * 100, 2),
                "unique_count": int(series.nunique(dropna=True)),
                "stats": _column_stats(series, label),
            }
        )
    return profiles


def quality_score(profiles: list[dict], duplicate_rows_removed: int, original_rows: int) -> float:
    """Heuristic, documented: 100 minus the average null % across columns,
    minus the % of original rows that were exact duplicates. Clamped to 0-100."""
    if not profiles:
        return 0.0
    avg_null = sum(p["null_pct"] for p in profiles) / len(profiles)
    dup_pct = (duplicate_rows_removed / original_rows * 100) if original_rows else 0.0
    return round(max(0.0, 100.0 - avg_null - dup_pct), 1)