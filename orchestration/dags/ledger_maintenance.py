"""
Ledger nightly maintenance.

  1. purge expired guest datasets (and their raw copies)
  2. re-profile datasets and record quality deltas / drift
  3. snapshot governed metrics whose data changed or whose snapshot went stale

The DAG only orchestrates. Every task calls an internal Ledger API endpoint, so the
logic lives (and is tested) in the Ledger codebase, not here.
"""

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta

try:
    from airflow.sdk import dag, task  # type: ignore[import-not-found]  # Airflow 3.x
except ImportError:  # Airflow 2.x
    from airflow.decorators import dag, task  # type: ignore[import-not-found]

API_URL = os.environ.get("LEDGER_API_URL", "http://api:8000").rstrip("/")
INTERNAL_SECRET = os.environ.get("LEDGER_INTERNAL_SECRET", "")


def call_api(path: str, timeout: int = 300) -> dict:
    """POST to an internal endpoint and return its JSON. Raises on any failure so Airflow retries."""
    if not INTERNAL_SECRET:
        raise RuntimeError("LEDGER_INTERNAL_SECRET is not set")
    request = urllib.request.Request(
        f"{API_URL}{path}", method="POST", headers={"X-Internal-Secret": INTERNAL_SECRET}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{path} returned HTTP {exc.code}") from None


@dag(
    dag_id="ledger_maintenance",
    schedule="17 3 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=2)},
    tags=["ledger"],
)
def ledger_maintenance():
    @task
    def purge_guest_data() -> dict:
        return call_api("/internal/maintenance/purge-guest-data")

    @task
    def reprofile_datasets() -> dict:
        return call_api("/internal/maintenance/reprofile")

    @task
    def snapshot_metrics() -> dict:
        return call_api("/internal/maintenance/snapshot-metrics")

    purge = purge_guest_data()
    reprofile = reprofile_datasets()
    snapshot = snapshot_metrics()
    purge >> reprofile >> snapshot


ledger_maintenance()