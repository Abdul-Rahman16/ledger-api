from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain import metric_service
from domain.freshness import change_pct, freshness_status
from domain.models import Dataset, MetricSnapshot, QualitySnapshot


def build_pipeline_status(
    db: Session,
    dataset: Dataset,
    *,
    stale_after: timedelta,
    now: datetime | None = None,
    history: int = 30,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc).replace(tzinfo=None)
    dataset_id = dataset.id

    quality_rows = db.execute(
        select(QualitySnapshot)
        .where(QualitySnapshot.dataset_id == dataset_id)
        .order_by(QualitySnapshot.taken_at.desc())
        .limit(history)
    ).scalars().all()
    quality_rows.reverse()  # oldest first, ready for a chart

    last_profiled = quality_rows[-1].taken_at if quality_rows else None
    status, age_hours = freshness_status(last_profiled, current, stale_after)

    metrics_out = []
    for metric in metric_service.list_active(db, dataset_id):
        rows = db.execute(
            select(MetricSnapshot)
            .where(MetricSnapshot.metric_id == metric.id)
            .order_by(MetricSnapshot.taken_at.desc())
            .limit(history)
        ).scalars().all()
        rows.reverse()
        latest = rows[-1] if rows else None
        previous = rows[-2] if len(rows) > 1 else None
        latest_value = latest.value if latest else None
        previous_value = previous.value if previous else None
        metrics_out.append(
            {
                "name": metric.name,
                "version": metric.version,
                "status": latest.status if latest else None,
                "taken_at": latest.taken_at if latest else None,
                "latest_value": latest_value,
                "previous_value": previous_value,
                "change_pct": change_pct(latest_value, previous_value),
                "history": [{"taken_at": r.taken_at, "value": r.value, "status": r.status} for r in rows],
            }
        )

    return {
        "freshness": {
            "status": status,
            "last_profiled_at": last_profiled,
            "stale_after_hours": int(stale_after.total_seconds() // 3600),
            "age_hours": age_hours,
        },
        "quality_history": [
            {
                "taken_at": r.taken_at,
                "row_count": r.row_count,
                "quality_score": r.quality_score,
                "quality_delta": r.quality_delta,
                "row_delta": r.row_delta,
                "changed": r.changed,
            }
            for r in quality_rows
        ],
        "metrics": metrics_out,
    }