"""
Smoke test for a deployed Ledger API (a guest session: no secret needed).

  python -m scripts.smoke_remote https://your-service.onrender.com

The first request can take up to a minute on Render's free plan (the service wakes up),
plus a few seconds if Neon's database is waking up too.
"""
import sys
from pathlib import Path

import httpx

SAMPLE = Path("sample_data/sales_sample.csv")


def step(label: str, response: httpx.Response, expected: set[int]) -> httpx.Response:
    ok = response.status_code in expected
    print(f"[{'ok' if ok else 'FAIL'}] {label}: HTTP {response.status_code}")
    if not ok:
        print("      ", response.text[:300])
        raise SystemExit(1)
    return response


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.smoke_remote https://your-service.onrender.com")
        raise SystemExit(2)
    base = sys.argv[1].rstrip("/")

    with httpx.Client(base_url=base, timeout=120) as client:
        step("health", client.get("/health"), {200})

        with open(SAMPLE, "rb") as handle:
            upload = step(
                "upload sample dataset",
                client.post("/datasets", files={"file": (SAMPLE.name, handle, "text/csv")}),
                {201},
            ).json()
        dataset_id = upload["id"]
        print(f"      dataset {dataset_id}: {upload['row_count']} rows, quality {upload['quality_score']}")

        step(
            "define metric",
            client.post(
                f"/datasets/{dataset_id}/metrics",
                json={
                    "name": "total_revenue",
                    "description": "Sum of completed order amounts",
                    "expression": "SUM(amount)",
                    "filter": "status = 'completed'",
                },
            ),
            {201},
        )

        query = step(
            "governed query",
            client.post(f"/datasets/{dataset_id}/query", json={"metric": "total_revenue", "group_by": "region"}),
            {200},
        ).json()
        print("      rows:", query["rows"])

        asked = step(
            "ask in plain English",
            client.post(f"/datasets/{dataset_id}/ask", json={"question": "Show total revenue by region"}),
            {200},
        ).json()
        print(f"      status={asked['status']} provider={asked['provider']} tokens={asked['tokens_used']}")
        print(f"      explanation ({asked['explanation_source']}): {asked['explanation']}")
        if asked["status"] != "answered":
            print("FAIL: the question was not answered:", asked.get("clarification"))
            raise SystemExit(1)

    print("All checks passed.")


if __name__ == "__main__":
    main()