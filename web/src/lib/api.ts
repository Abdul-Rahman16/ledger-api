import type { DatasetDetail } from "./types.ts";
import { extractDetail, friendlyError } from "./upload.ts";

export class ApiError extends Error {
    status: number | null;

    constructor(status: number | null, message: string) {
        super(message);
        this.name = "ApiError";
        this.status = status;
    }
}

interface UploadHandlers {
    onProgress?: (percent: number) => void;
    /** Called once the whole file has reached the server and profiling begins. */
    onUploaded?: () => void;
    signal?: AbortSignal;
}

/** Uploads through the same-origin proxy. XMLHttpRequest is used because fetch cannot report upload progress. */
export function uploadDataset(file: File, handlers: UploadHandlers = {}): Promise<DatasetDetail> {
    return new Promise<DatasetDetail>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/ledger/datasets");
        xhr.timeout = 120_000;

        xhr.upload.onprogress = (event) => {
            if (event.lengthComputable && event.total > 0) {
                handlers.onProgress?.(Math.round((event.loaded / event.total) * 100));
            }
        };
        xhr.upload.onload = () => handlers.onUploaded?.();

        xhr.onload = () => {
            let body: unknown = null;
            try {
                body = JSON.parse(xhr.responseText);
            } catch {
                body = null;
            }
            if (xhr.status === 201 && typeof body === "object" && body !== null) {
                resolve(body as DatasetDetail);
            } else {
                reject(new ApiError(xhr.status, friendlyError(xhr.status, extractDetail(body))));
            }
        };
        xhr.onerror = () => reject(new ApiError(null, friendlyError(null, null)));
        xhr.ontimeout = () => reject(new ApiError(504, friendlyError(504, null)));
        xhr.onabort = () => reject(new DOMException("Upload cancelled", "AbortError"));

        handlers.signal?.addEventListener("abort", () => xhr.abort(), { once: true });

        const form = new FormData();
        form.append("file", file, file.name);
        xhr.send(form);
    });
}

/** Wakes the API (Render's free plan sleeps when idle) while the visitor is still choosing a file. */
export function warmUpApi(): void {
    void fetch("/api/ledger/health", { cache: "no-store" }).catch(() => undefined);
}