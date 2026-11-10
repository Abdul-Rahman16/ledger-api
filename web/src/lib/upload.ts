import { ACCEPTED_EXTENSIONS, MAX_UPLOAD_BYTES } from "./config.ts";

export type FileCheck = { ok: true } | { ok: false; message: string };

export function validateFile(file: { name: string; size: number }): FileCheck {
    const lower = file.name.toLowerCase();
    if (!ACCEPTED_EXTENSIONS.some((extension) => lower.endsWith(extension))) {
        return { ok: false, message: "Unsupported file type. Use a CSV, XLSX or JSON file." };
    }
    if (file.size === 0) return { ok: false, message: "That file is empty." };
    if (file.size > MAX_UPLOAD_BYTES) {
        return { ok: false, message: `That file is larger than ${MAX_UPLOAD_BYTES / (1024 * 1024)} MB.` };
    }
    return { ok: true };
}

/** FastAPI errors are either {detail: "text"} or {detail: [{msg: "text"}, ...]}. */
export function extractDetail(body: unknown): string | null {
    if (typeof body !== "object" || body === null || !("detail" in body)) return null;
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
        const messages = detail
            .map((entry) => (typeof entry === "object" && entry !== null && "msg" in entry ? String((entry as { msg: unknown }).msg) : ""))
            .filter(Boolean);
        return messages.length > 0 ? messages.join(" ") : null;
    }
    return null;
}

/** Turns an API failure into a message a person can act on. status is null for network failures. */
export function friendlyError(status: number | null, detail: string | null): string {
    if (status === null || status === 0) return "Could not reach the server. Check your connection and try again.";
    if (status === 413) return "That file is too large to upload.";
    if (status === 429) return "Too many requests. Please wait a minute and try again.";
    if (status === 502 || status === 503 || status === 504) {
        return "The service is waking up. Give it a few seconds and try again.";
    }
    if (status === 422 && detail) return detail;
    if (status >= 500) return "Something went wrong on our side. Please try again.";
    return detail ?? "The upload failed. Please try again.";
}

export type UploadState =
    | { phase: "idle" }
    | { phase: "uploading"; fileName: string; progress: number }
    | { phase: "profiling"; fileName: string }
    | { phase: "done"; fileName: string; datasetId: string }
    | { phase: "error"; message: string };

export type UploadAction =
    | { type: "start"; fileName: string }
    | { type: "progress"; progress: number }
    | { type: "uploaded" }
    | { type: "succeeded"; datasetId: string }
    | { type: "failed"; message: string }
    | { type: "reset" };

export function uploadReducer(state: UploadState, action: UploadAction): UploadState {
    switch (action.type) {
        case "start":
            return { phase: "uploading", fileName: action.fileName, progress: 0 };
        case "progress":
            if (state.phase !== "uploading") return state;
            return { ...state, progress: Math.min(100, Math.max(state.progress, Math.round(action.progress))) };
        case "uploaded":
            if (state.phase !== "uploading") return state;
            return { phase: "profiling", fileName: state.fileName };
        case "succeeded":
            if (state.phase !== "uploading" && state.phase !== "profiling") return state;
            return { phase: "done", fileName: state.fileName, datasetId: action.datasetId };
        case "failed":
            if (state.phase === "idle" || state.phase === "done") return state;
            return { phase: "error", message: action.message };
        case "reset":
            return { phase: "idle" };
    }
}