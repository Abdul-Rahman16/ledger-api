import assert from "node:assert/strict";
import { test } from "node:test";

import {
    MAX_RECENT,
    RECENT_KEY,
    addRecent,
    loadRecent,
    parseRecent,
    pruneExpired,
    removeRecent,
    saveRecent,
    type RecentDataset,
} from "../src/lib/recent.ts";

function entry(id: string, overrides: Partial<RecentDataset> = {}): RecentDataset {
    return { id, name: `ds-${id}`, fileName: `${id}.csv`, rows: 10, columns: 3, qualityScore: 100, savedAt: "2026-11-03T12:00:00Z", ...overrides };
}

test("addRecent puts the newest first, dedupes by id and caps the list", () => {
    let list: RecentDataset[] = [];
    for (let index = 1; index <= MAX_RECENT + 2; index += 1) list = addRecent(list, entry(String(index)));
    assert.equal(list.length, MAX_RECENT);
    assert.equal(list[0].id, String(MAX_RECENT + 2));

    const again = addRecent(list, entry("5", { name: "renamed" }));
    assert.equal(again[0].id, "5");
    assert.equal(again[0].name, "renamed");
    assert.equal(again.filter((item) => item.id === "5").length, 1);
    assert.equal(again.length, MAX_RECENT);
});

test("removeRecent", () => {
    assert.deepEqual(removeRecent([entry("a"), entry("b")], "a").map((item) => item.id), ["b"]);
    assert.deepEqual(removeRecent([entry("a")], "zzz").map((item) => item.id), ["a"]);
});

test("parseRecent survives corrupt or hostile storage contents", () => {
    assert.deepEqual(parseRecent(null), []);
    assert.deepEqual(parseRecent(""), []);
    assert.deepEqual(parseRecent("{not json"), []);
    assert.deepEqual(parseRecent('{"id":"x"}'), []);
    assert.deepEqual(parseRecent('"text"'), []);
    const mixed = JSON.stringify([entry("ok"), { id: 5 }, null, "x", { ...entry("bad"), rows: "ten" }]);
    assert.deepEqual(parseRecent(mixed).map((item) => item.id), ["ok"]);
    const many = JSON.stringify(Array.from({ length: 20 }, (_, index) => entry(String(index))));
    assert.equal(parseRecent(many).length, MAX_RECENT);
});

test("load and save go through the storage they are given, and never throw", () => {
    const store = new Map<string, string>();
    const storage = {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => void store.set(key, value),
    };
    saveRecent([entry("a"), entry("b")], storage);
    assert.ok(store.has(RECENT_KEY));
    assert.deepEqual(loadRecent(storage).map((item) => item.id), ["a", "b"]);

    const broken = {
        getItem: () => {
            throw new Error("denied");
        },
        setItem: () => {
            throw new Error("quota");
        },
    };
    assert.deepEqual(loadRecent(broken), []);
    assert.doesNotThrow(() => saveRecent([entry("a")], broken));
});

test("pruneExpired drops datasets the server has already deleted", () => {
    const now = new Date("2026-11-03T12:00:00Z");
    const hoursAgo = (hours: number) => new Date(now.getTime() - hours * 3_600_000).toISOString();
    const list = [
        entry("fresh", { savedAt: hoursAgo(2) }),
        entry("edge", { savedAt: hoursAgo(24) }),
        entry("old", { savedAt: hoursAgo(25) }),
        entry("junk", { savedAt: "not a date" }),
    ];
    assert.deepEqual(pruneExpired(list, now, 24).map((item) => item.id), ["fresh", "edge"]);
});