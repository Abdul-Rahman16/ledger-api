import assert from "node:assert/strict";
import { test } from "node:test";

import { columnHealth, completeness, findings, nullPercent, qualityBand, statLine } from "../src/lib/quality.ts";
import type { ColumnProfile } from "../src/lib/types.ts";

function column(overrides: Partial<ColumnProfile> = {}): ColumnProfile {
    return {
        name: "amount",
        position: 0,
        dtype: "float",
        null_pct: 0,
        unique_count: 6,
        stats: { min: 15.75, max: 230.25, mean: 93.5817 },
        ...overrides,
    };
}

test("quality bands", () => {
    assert.deepEqual(qualityBand(100), { label: "Excellent", tone: "excellent" });
    assert.deepEqual(qualityBand(90), { label: "Excellent", tone: "excellent" });
    assert.deepEqual(qualityBand(89.9), { label: "Good", tone: "good" });
    assert.deepEqual(qualityBand(73.8), { label: "Needs attention", tone: "attention" });
    assert.deepEqual(qualityBand(49.9), { label: "Poor", tone: "poor" });
    assert.deepEqual(qualityBand(null), { label: "Not scored", tone: "unknown" });
});

test("nullPercent clamps to 0-100", () => {
    assert.equal(nullPercent({ null_pct: 16.7 }), 16.7);
    assert.equal(nullPercent({ null_pct: -3 }), 0);
    assert.equal(nullPercent({ null_pct: 140 }), 100);
});

test("completeness averages columns", () => {
    assert.equal(completeness([]), null);
    assert.equal(completeness([{ null_pct: 0 }, { null_pct: 0 }]), 100);
    assert.equal(completeness([{ null_pct: 10 }, { null_pct: 30 }]), 80);
    assert.equal(completeness([{ null_pct: 16.6667 }, { null_pct: 0 }, { null_pct: 0 }]), 94.4);
});

test("column health", () => {
    assert.equal(columnHealth({ null_pct: 0 }), "complete");
    assert.equal(columnHealth({ null_pct: 5 }), "gaps");
    assert.equal(columnHealth({ null_pct: 20 }), "sparse");
});

test("findings are derived from the profile and sorted warnings first", () => {
    const columns = [
        column({ name: "order_id", dtype: "integer", unique_count: 10 }),
        column({ name: "region", dtype: "text", null_pct: 8.3, unique_count: 4, stats: null }),
        column({ name: "status", dtype: "text", unique_count: 1, stats: null }),
        column({ name: "notes", dtype: "text", null_pct: 40, unique_count: 3, stats: null }),
    ];
    const result = findings(columns, 10);
    assert.deepEqual(
        result.map((item) => [item.severity, item.column]),
        [
            ["warning", "notes"],
            ["info", "order_id"],
            ["info", "region"],
            ["info", "status"],
        ],
    );
    assert.match(result[0].message, /missing 40% of its values/);
});

test("fully empty columns are a warning and constant columns need more than one row", () => {
    const empty = findings([column({ name: "x", null_pct: 100, unique_count: 0 })], 10);
    assert.deepEqual(empty, [{ severity: "warning", column: "x", message: "has no values at all" }]);
    assert.deepEqual(findings([column({ unique_count: 1 })], 1), []);
    assert.equal(findings([column({ unique_count: 1 })], 5)[0].message, "has the same value in every row");
});

test("identifier detection needs enough rows and complete data", () => {
    assert.equal(findings([column({ dtype: "integer", unique_count: 3 })], 3).length, 0);
    assert.equal(findings([column({ dtype: "float", unique_count: 8 })], 8).length, 0);
    assert.equal(findings([column({ dtype: "integer", unique_count: 8 })], 8).length, 1);
});

test("a clean profile has no findings", () => {
    assert.deepEqual(findings([column({ unique_count: 4 })], 10), []);
});

test("statLine summarises each column type", () => {
    assert.equal(statLine(column()), "15.75 \u2013 230.25 \u00b7 mean 93.58");
    assert.equal(
        statLine(column({ dtype: "datetime", stats: { min: "2026-01-05T00:00:00", max: "2026-01-10T00:00:00" } })),
        "2026-01-05 \u2192 2026-01-10",
    );
    const text = column({
        dtype: "text",
        stats: { top_values: [{ value: "North", count: 2 }, { value: "South", count: 2 }, { value: null, count: 1 }, { value: "East", count: 1 }] },
    });
    assert.equal(statLine(text), "North, South, (blank), \u2026");
    assert.equal(statLine(column({ stats: null })), "\u2014");
    assert.equal(statLine(column({ dtype: "text", stats: {} })), "\u2014");
});