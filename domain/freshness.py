"""
Pure helpers for pipeline freshness: profile fingerprints, freshness status, metric refresh decisions.
No database or network access, so they are cheap to test.
"""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Sequence


def profile_fingerprint(row_count: int, columns: Sequence[dict[str, Any]]) -> str:
    """A stable hash of the row count and the per-column profile. If it changes, the data changed."""
    payload = {
        "rows": row_count,
        "columns": [
            [col["name"], col["dtype"], col["null_pct"], col["unique_count"], col.get("stats")]
            for col in columns
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def freshness_status(
    last_profiled_at: datetime | None, now: datetime, stale_after: timedelta
) -> tuple[str, float | None]:
    """Returns (status, age in hours). status is never_profiled, fresh or stale."""
    if last_profiled_at is None:
        return "never_profiled", None
    age = now - last_profiled_at
    return ("fresh" if age <= stale_after else "stale"), round(age.total_seconds() / 3600, 2)


def change_pct(latest: float | None, previous: float | None) -> float | None:
    if latest is None or previous is None or previous == 0:
        return None
    return round((latest - previous) / abs(previous) * 100, 1)


def needs_metric_refresh(
    *,
    last_taken_at: datetime | None,
    data_changed_at: datetime | None,
    now: datetime,
    refresh_after: timedelta,
) -> str | None:
    """The reason a new metric snapshot is needed, or None while the latest one is still fresh."""
    if last_taken_at is None:
        return "never computed"
    if data_changed_at is not None and data_changed_at > last_taken_at:
        return "data changed"
    if now - last_taken_at >= refresh_after:
        return "stale"
    return None