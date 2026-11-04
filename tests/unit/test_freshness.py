from datetime import datetime, timedelta

from domain.freshness import change_pct, freshness_status, needs_metric_refresh, profile_fingerprint

NOW = datetime(2026, 11, 4, 12, 0, 0)
HOUR = timedelta(hours=1)
COLUMNS = [
    {"name": "amount", "dtype": "float", "null_pct": 0.0, "unique_count": 2, "stats": {"min": 10.5, "max": 20.0}},
    {"name": "status", "dtype": "text", "null_pct": 0.0, "unique_count": 1, "stats": {"top_values": [{"value": "a", "count": 2}]}},
]


def test_fingerprint_is_stable_and_sensitive_to_every_part_of_the_profile():
    base = profile_fingerprint(2, COLUMNS)
    assert base == profile_fingerprint(2, [dict(col) for col in COLUMNS])
    assert len(base) == 64
    assert profile_fingerprint(3, COLUMNS) != base                      # row count
    changed_stats = [dict(COLUMNS[0], stats={"min": 10.5, "max": 21.0}), COLUMNS[1]]
    assert profile_fingerprint(2, changed_stats) != base                # a statistic
    changed_type = [dict(COLUMNS[0], dtype="integer"), COLUMNS[1]]
    assert profile_fingerprint(2, changed_type) != base                 # a type
    assert profile_fingerprint(2, list(reversed(COLUMNS))) != base      # column order matters
    key_order = [{"stats": col["stats"], "unique_count": col["unique_count"], "null_pct": col["null_pct"],
                  "dtype": col["dtype"], "name": col["name"]} for col in COLUMNS]
    assert profile_fingerprint(2, key_order) == base                    # dict key order does not


def test_fingerprint_handles_missing_stats_and_unusual_numbers():
    no_stats = [{"name": "a", "dtype": "text", "null_pct": 0.0, "unique_count": 1}]
    assert len(profile_fingerprint(1, no_stats)) == 64

    class Number:  # stands in for numpy scalars, which json cannot serialise natively
        def __str__(self):
            return "1.5"

    odd = [{"name": "a", "dtype": "float", "null_pct": 0.0, "unique_count": 1, "stats": {"mean": Number()}}]
    assert len(profile_fingerprint(1, odd)) == 64


def test_freshness_status():
    day = timedelta(hours=24)
    assert freshness_status(None, NOW, day) == ("never_profiled", None)
    assert freshness_status(NOW - 2 * HOUR, NOW, day) == ("fresh", 2.0)
    assert freshness_status(NOW - day, NOW, day) == ("fresh", 24.0)          # exactly on the limit is fresh
    assert freshness_status(NOW - day - HOUR, NOW, day) == ("stale", 25.0)
    assert freshness_status(NOW - timedelta(minutes=90), NOW, day) == ("fresh", 1.5)


def test_change_pct():
    assert change_pct(150.0, 100.0) == 50.0
    assert change_pct(75.0, 100.0) == -25.0
    assert change_pct(100.0, 0.0) is None
    assert change_pct(None, 100.0) is None and change_pct(100.0, None) is None
    assert change_pct(-50.0, -100.0) == 50.0
    assert change_pct(1.0, 3.0) == -66.7


def test_metric_refresh_decisions():
    refresh_after = timedelta(hours=24)

    def decide(last, changed):
        return needs_metric_refresh(last_taken_at=last, data_changed_at=changed, now=NOW, refresh_after=refresh_after)

    assert decide(None, None) == "never computed"
    assert decide(None, NOW) == "never computed"
    assert decide(NOW - 2 * HOUR, None) is None                                  # fresh and unchanged
    assert decide(NOW - 2 * HOUR, NOW - 5 * HOUR) is None                        # data changed before the snapshot
    assert decide(NOW - 5 * HOUR, NOW - 2 * HOUR) == "data changed"
    assert decide(NOW - 25 * HOUR, None) == "stale"
    assert decide(NOW - 24 * HOUR, None) == "stale"                              # on the limit counts as stale
    assert decide(NOW - 30 * HOUR, NOW - 29 * HOUR) == "data changed"            # change wins over staleness