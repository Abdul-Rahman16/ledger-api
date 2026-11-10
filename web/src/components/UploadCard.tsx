"use client";

import { useCallback, useReducer, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "motion/react";

import { ApiError, uploadDataset } from "@/lib/api";
import {
    ACCEPTED_EXTENSIONS,
    GUEST_RETENTION_HOURS,
    MAX_COLUMNS,
    MAX_ROWS,
    MAX_UPLOAD_BYTES,
    SAMPLE_DATASETS,
} from "@/lib/config";
import { formatBytes, formatNumber } from "@/lib/format";
import { addRecent, loadRecent, saveRecent } from "@/lib/recent";
import { uploadReducer, validateFile } from "@/lib/upload";

const STEPS = ["Uploading your file", "Profiling columns", "Opening your dataset"] as const;

type StepStatus = "done" | "active" | "pending";

function stepStatus(phase: string, index: number): StepStatus {
    const current = phase === "uploading" ? 0 : phase === "profiling" ? 1 : 2;
    if (index < current) return "done";
    return index === current ? "active" : "pending";
}

function StepIcon({ status }: { status: StepStatus }) {
    if (status === "done") {
        return (
            <span className="flex size-5 items-center justify-center rounded-full bg-emerald-500 text-white">
                <svg viewBox="0 0 20 20" className="size-3.5" fill="currentColor" aria-hidden="true">
                    <path d="M8.2 13.6 4.9 10.3l1.1-1.1 2.2 2.2 5.8-5.8 1.1 1.1-6.9 6.9Z" />
                </svg>
            </span>
        );
    }
    if (status === "active") {
        return <span className="size-5 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600" />;
    }
    return <span className="size-5 rounded-full border-2 border-slate-200" />;
}

export function UploadCard() {
    const router = useRouter();
    const [state, dispatch] = useReducer(uploadReducer, { phase: "idle" });
    const [dragging, setDragging] = useState(false);
    const inputRef = useRef<HTMLInputElement>(null);
    const abortRef = useRef<AbortController | null>(null);

    const busy = state.phase === "uploading" || state.phase === "profiling" || state.phase === "done";

    const handleFile = useCallback(
        async (file: File) => {
            const check = validateFile(file);
            if (!check.ok) {
                dispatch({ type: "start", fileName: file.name });
                dispatch({ type: "failed", message: check.message });
                return;
            }

            const controller = new AbortController();
            abortRef.current = controller;
            dispatch({ type: "start", fileName: file.name });
            try {
                const dataset = await uploadDataset(file, {
                    signal: controller.signal,
                    onProgress: (progress) => dispatch({ type: "progress", progress }),
                    onUploaded: () => dispatch({ type: "uploaded" }),
                });
                saveRecent(
                    addRecent(loadRecent(), {
                        id: dataset.id,
                        name: dataset.name,
                        fileName: dataset.original_filename,
                        rows: dataset.row_count,
                        columns: dataset.column_count,
                        qualityScore: dataset.quality_score,
                        savedAt: new Date().toISOString(),
                    }),
                );
                dispatch({ type: "succeeded", datasetId: dataset.id });
                router.push(`/d/${dataset.id}`);
            } catch (error) {
                if (error instanceof DOMException && error.name === "AbortError") {
                    dispatch({ type: "reset" });
                    return;
                }
                dispatch({
                    type: "failed",
                    message: error instanceof ApiError ? error.message : "The upload failed. Please try again.",
                });
            } finally {
                abortRef.current = null;
            }
        },
        [router],
    );

    const loadSample = useCallback(
        async (sample: (typeof SAMPLE_DATASETS)[number]) => {
            try {
                const response = await fetch(sample.url);
                if (!response.ok) throw new Error("sample unavailable");
                const blob = await response.blob();
                await handleFile(new File([blob], sample.fileName, { type: "text/csv" }));
            } catch {
                dispatch({ type: "start", fileName: sample.fileName });
                dispatch({ type: "failed", message: "Could not load the sample file." });
            }
        },
        [handleFile],
    );

    return (
        <div className="rounded-2xl border border-slate-200 bg-white p-2 shadow-[0_1px_2px_rgba(15,23,42,0.04),0_12px_32px_-12px_rgba(15,23,42,0.12)]">
            <AnimatePresence mode="wait" initial={false}>
                {busy ? (
                    <motion.div
                        key="progress"
                        initial={{ opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        className="rounded-xl bg-slate-50 px-6 py-8 sm:px-10"
                        role="status"
                        aria-live="polite"
                    >
                        <p className="truncate text-sm font-medium text-slate-900">{state.fileName}</p>
                        <ol className="mt-5 space-y-4">
                            {STEPS.map((label, index) => {
                                const status = stepStatus(state.phase, index);
                                return (
                                    <li key={label} className="flex items-center gap-3">
                                        <StepIcon status={status} />
                                        <span className={status === "pending" ? "text-sm text-slate-400" : "text-sm font-medium text-slate-800"}>
                                            {label}
                                        </span>
                                        {index === 0 && state.phase === "uploading" ? (
                                            <span className="ml-auto text-xs tabular-nums text-slate-500">{state.progress}%</span>
                                        ) : null}
                                    </li>
                                );
                            })}
                        </ol>

                        <div className="mt-6 h-1.5 overflow-hidden rounded-full bg-slate-200">
                            {state.phase === "uploading" ? (
                                <motion.div
                                    className="h-full rounded-full bg-indigo-600"
                                    initial={false}
                                    animate={{ width: `${state.progress}%` }}
                                    transition={{ duration: 0.25, ease: "easeOut" }}
                                />
                            ) : state.phase === "profiling" ? (
                                <div className="indeterminate-bar h-full w-1/3 rounded-full bg-indigo-600" />
                            ) : (
                                <div className="h-full w-full rounded-full bg-emerald-500" />
                            )}
                        </div>
                        <p className="mt-3 text-xs text-slate-500">
                            {state.phase === "profiling"
                                ? "Detecting column types, counting blanks and scoring data quality. The first request can take up to a minute while the service wakes up."
                                : state.phase === "uploading"
                                    ? "Sending your file securely."
                                    : "Done. Taking you to the results."}
                        </p>
                        {state.phase === "uploading" ? (
                            <button
                                type="button"
                                onClick={() => abortRef.current?.abort()}
                                className="mt-4 text-xs font-medium text-slate-500 underline-offset-2 hover:text-slate-800 hover:underline"
                            >
                                Cancel
                            </button>
                        ) : null}
                    </motion.div>
                ) : (
                    <motion.div
                        key="idle"
                        initial={{ opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.2 }}
                    >
                        <label
                            onDragOver={(event) => {
                                event.preventDefault();
                                setDragging(true);
                            }}
                            onDragLeave={() => setDragging(false)}
                            onDrop={(event) => {
                                event.preventDefault();
                                setDragging(false);
                                const file = event.dataTransfer.files?.[0];
                                if (file) void handleFile(file);
                            }}
                            className={`flex cursor-pointer flex-col items-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors sm:px-10 ${dragging ? "border-indigo-500 bg-indigo-50" : "border-slate-200 bg-slate-50/60 hover:border-indigo-300 hover:bg-indigo-50/40"
                                }`}
                        >
                            <span className="flex size-11 items-center justify-center rounded-full bg-white text-indigo-600 shadow-sm ring-1 ring-slate-200">
                                <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                                    <path d="M12 16V4m0 0-4 4m4-4 4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
                                </svg>
                            </span>
                            <span className="mt-4 text-[15px] font-semibold text-slate-900">Drop a file here, or click to browse</span>
                            <span className="mt-1 text-sm text-slate-500">
                                {ACCEPTED_EXTENSIONS.map((extension) => extension.slice(1).toUpperCase()).join(", ")} · up to{" "}
                                {formatBytes(MAX_UPLOAD_BYTES)} · {formatNumber(MAX_ROWS, 0)} rows · {MAX_COLUMNS} columns
                            </span>
                            <input
                                ref={inputRef}
                                type="file"
                                accept={ACCEPTED_EXTENSIONS.join(",")}
                                className="sr-only"
                                onChange={(event) => {
                                    const file = event.target.files?.[0];
                                    event.target.value = "";
                                    if (file) void handleFile(file);
                                }}
                            />
                        </label>

                        {state.phase === "error" ? (
                            <div role="alert" className="mx-2 mt-3 flex items-start gap-2.5 rounded-lg bg-rose-50 px-3.5 py-3 text-sm text-rose-800 ring-1 ring-rose-200">
                                <svg viewBox="0 0 20 20" className="mt-0.5 size-4 shrink-0" fill="currentColor" aria-hidden="true">
                                    <path d="M10 2a8 8 0 1 0 0 16 8 8 0 0 0 0-16Zm-.75 4.5h1.5v5h-1.5v-5Zm.75 8.25a.9.9 0 1 1 0-1.8.9.9 0 0 1 0 1.8Z" />
                                </svg>
                                <span className="flex-1">{state.message}</span>
                                <button
                                    type="button"
                                    onClick={() => dispatch({ type: "reset" })}
                                    className="text-xs font-semibold text-rose-700 hover:underline"
                                >
                                    Dismiss
                                </button>
                            </div>
                        ) : null}

                        <div className="flex flex-col gap-3 px-3 pb-3 pt-4 sm:flex-row sm:items-center sm:justify-between">
                            <div className="flex flex-wrap items-center gap-2">
                                <span className="text-xs font-medium text-slate-500">No file handy?</span>
                                {SAMPLE_DATASETS.map((sample) => (
                                    <button
                                        key={sample.id}
                                        type="button"
                                        title={sample.description}
                                        onClick={() => void loadSample(sample)}
                                        className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-700 shadow-sm transition hover:border-indigo-300 hover:text-indigo-700"
                                    >
                                        {sample.label}
                                    </button>
                                ))}
                            </div>
                            <p className="text-xs text-slate-500">
                                Guest mode: your dataset is deleted after {GUEST_RETENTION_HOURS} hours.
                            </p>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}