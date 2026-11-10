import assert from "node:assert/strict";
import { test } from "node:test";

import {
    dateOnly,
    formatBytes,
    formatNumber,
    formatPercent,
    hoursLeft,
    humanizeDtype,
    parseApiDate,
    timeAgo,
    truncate,
} from "../src/lib/format.ts";

test("formatNumber groups thousands, limits decimals and handles missing values", () => {
    assert.equal(formatNumber(1234567.891), "1,234,567.89");
    assert.equal(formatNumber(105.5), "105.5");
    assert.equal(formatNumber(0), "0");
    assert.equal(formatNumber(1234.5678, 0), "1,235");
    assert.equal(formatNumber(null), "\u2014");
    assert.equal(formatNumber(undefined), "\u2014");
    assert.equal(formatNumber(Number.NaN), "\u2014");
});

test("formatBytes", () => {
    assert.equal(formatBytes(512), "512 B");
    assert.equal(formatBytes(2048), "2.0 KB");
    assert.equal(formatBytes(4 * 1024 * 1024), "4.0 MB");
    assert.equal(formatBytes(-1), "\u2014");
});

test("formatPercent trims trailing zeros", () => {
    assert.equal(formatPercent(0), "0%");
    assert.equal(formatPercent(12.5), "12.5%");
    assert.equal(formatPercent(16.6667), "16.7%");
    assert.equal(formatPercent(100), "100%");
    assert.equal(formatPercent(null), "\u2014");
});

test("API timestamps without a zone are read as UTC", () => {
    assert.equal(parseApiDate("2026-11-03T17:14:00.408309").toISOString(), "2026-11-03T17:14:00.408Z");
    assert.equal(parseApiDate("2026-11-03T17:14:00Z").toISOString(), "2026-11-03T17:14:00.000Z");
    assert.equal(parseApiDate("2026-11-03T17:14:00+05:30").toISOString(), "2026-11-03T11:44:00.000Z");
});

test("timeAgo", () => {
    const now = new Date("2026-11-03T12:00:00Z");
    const ago = (seconds: number) => timeAgo(new Date(now.getTime() - seconds * 1000), now);
    assert.equal(ago(5), "just now");
    assert.equal(ago(10 * 60), "10 min ago");
    assert.equal(ago(3 * 3600), "3 h ago");
    assert.equal(ago(2 * 86400), "2 d ago");
    assert.equal(timeAgo(new Date("nope"), now), "");
});

test("truncate, humanizeDtype and dateOnly", () => {
    assert.equal(truncate("abcdef", 10), "abcdef");
    assert.equal(truncate("abcdefghij", 5), "abcd\u2026");
    assert.equal(humanizeDtype("float"), "Decimal");
    assert.equal(humanizeDtype("datetime"), "Date/time");
    assert.equal(humanizeDtype("boolean"), "Boolean");
    assert.equal(dateOnly("2026-01-05T00:00:00"), "2026-01-05");
});

test("hoursLeft counts down to deletion and never goes negative", () => {
    const now = new Date("2026-11-03T12:00:00Z");
    const created = (hoursAgo: number) => new Date(now.getTime() - hoursAgo * 3_600_000);
    assert.equal(hoursLeft(created(0), 24, now), 24);
    assert.equal(hoursLeft(created(23.5), 24, now), 1);
    assert.equal(hoursLeft(created(24), 24, now), 0);
    assert.equal(hoursLeft(created(30), 24, now), 0);
    assert.equal(hoursLeft(new Date("nope"), 24, now), 0);
});