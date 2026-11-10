import assert from "node:assert/strict";
import { test } from "node:test";

import { MAX_UPLOAD_BYTES } from "../src/lib/config.ts";
import {
    extractDetail,
    friendlyError,
    uploadReducer,
    validateFile,
    type UploadAction,
    type UploadState,
} from "../src/lib/upload.ts";

test("validateFile accepts the supported types, in any case", () => {
    for (const name of ["sales.csv", "Sales.CSV", "book.xlsx", "data.json"]) {
        assert.deepEqual(validateFile({ name, size: 1000 }), { ok: true }, name);
    }
});

test("validateFile rejects bad types, empty files and oversized files", () => {
    const type = validateFile({ name: "malware.exe", size: 10 });
    assert.equal(type.ok, false);
    assert.match(!type.ok ? type.message : "", /Unsupported file type/);
    assert.equal(validateFile({ name: "csv", size: 10 }).ok, false);
    assert.equal(validateFile({ name: "a.csv.exe", size: 10 }).ok, false);

    const empty = validateFile({ name: "a.csv", size: 0 });
    assert.equal(!empty.ok && empty.message, "That file is empty.");

    assert.equal(validateFile({ name: "a.csv", size: MAX_UPLOAD_BYTES }).ok, true);
    const big = validateFile({ name: "a.csv", size: MAX_UPLOAD_BYTES + 1 });
    assert.equal(!big.ok && big.message, "That file is larger than 4 MB.");
});

test("extractDetail reads both FastAPI error shapes", () => {
    assert.equal(extractDetail({ detail: "The uploaded file is empty." }), "The uploaded file is empty.");
    assert.equal(extractDetail({ detail: [{ msg: "Field required" }, { msg: "Bad value" }] }), "Field required Bad value");
    assert.equal(extractDetail({ detail: [] }), null);
    assert.equal(extractDetail({ detail: 5 }), null);
    assert.equal(extractDetail({}), null);
    assert.equal(extractDetail(null), null);
    assert.equal(extractDetail("text"), null);
});

test("friendlyError maps statuses to actionable messages", () => {
    assert.match(friendlyError(null, null), /Could not reach the server/);
    assert.match(friendlyError(0, null), /Could not reach the server/);
    assert.match(friendlyError(413, null), /too large/);
    assert.match(friendlyError(429, "ignored"), /Too many requests/);
    assert.match(friendlyError(504, null), /waking up/);
    assert.match(friendlyError(503, "x"), /waking up/);
    assert.equal(friendlyError(422, "Unsupported file type '.exe'."), "Unsupported file type '.exe'.");
    assert.match(friendlyError(422, null), /upload failed/);
    assert.match(friendlyError(500, "internal detail"), /our side/);
    assert.ok(!friendlyError(500, "internal detail").includes("internal detail"));
});

function run(actions: UploadAction[], from: UploadState = { phase: "idle" }): UploadState {
    return actions.reduce(uploadReducer, from);
}

test("the happy path moves idle -> uploading -> profiling -> done", () => {
    assert.deepEqual(run([{ type: "start", fileName: "a.csv" }]), { phase: "uploading", fileName: "a.csv", progress: 0 });
    assert.deepEqual(
        run([{ type: "start", fileName: "a.csv" }, { type: "progress", progress: 42.4 }]),
        { phase: "uploading", fileName: "a.csv", progress: 42 },
    );
    assert.deepEqual(
        run([{ type: "start", fileName: "a.csv" }, { type: "uploaded" }]),
        { phase: "profiling", fileName: "a.csv" },
    );
    assert.deepEqual(
        run([{ type: "start", fileName: "a.csv" }, { type: "uploaded" }, { type: "succeeded", datasetId: "d1" }]),
        { phase: "done", fileName: "a.csv", datasetId: "d1" },
    );
});

test("progress never goes backwards and is clamped", () => {
    const state = run([
        { type: "start", fileName: "a.csv" },
        { type: "progress", progress: 60 },
        { type: "progress", progress: 30 },
        { type: "progress", progress: 250 },
    ]);
    assert.equal(state.phase === "uploading" && state.progress, 100);
});

test("actions in the wrong phase are ignored", () => {
    const idle: UploadState = { phase: "idle" };
    assert.deepEqual(uploadReducer(idle, { type: "progress", progress: 10 }), idle);
    assert.deepEqual(uploadReducer(idle, { type: "uploaded" }), idle);
    assert.deepEqual(uploadReducer(idle, { type: "succeeded", datasetId: "x" }), idle);
    assert.deepEqual(uploadReducer(idle, { type: "failed", message: "x" }), idle);
    const profiling: UploadState = { phase: "profiling", fileName: "a.csv" };
    assert.deepEqual(uploadReducer(profiling, { type: "progress", progress: 10 }), profiling);
    assert.deepEqual(uploadReducer(profiling, { type: "uploaded" }), profiling);
});

test("failures and resets", () => {
    const failed = run([{ type: "start", fileName: "a.csv" }, { type: "failed", message: "Nope" }]);
    assert.deepEqual(failed, { phase: "error", message: "Nope" });
    assert.deepEqual(uploadReducer(failed, { type: "reset" }), { phase: "idle" });
    const done = run([{ type: "start", fileName: "a.csv" }, { type: "succeeded", datasetId: "d" }]);
    assert.deepEqual(uploadReducer(done, { type: "failed", message: "late" }), done); // a finished upload stays finished
    assert.deepEqual(
        uploadReducer(failed, { type: "start", fileName: "b.csv" }),
        { phase: "uploading", fileName: "b.csv", progress: 0 },
    );
});