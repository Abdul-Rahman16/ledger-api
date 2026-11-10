// Guests have no dataset list on the server, so the browser remembers the datasets it created.

export interface RecentDataset {
    id: string;
    name: string;
    fileName: string;
    rows: number | null;
    columns: number | null;
    qualityScore: number | null;
    savedAt: string;
}

export const RECENT_KEY = "ledger.recent.v1";
export const MAX_RECENT = 6;

export function addRecent(list: RecentDataset[], entry: RecentDataset, max: number = MAX_RECENT): RecentDataset[] {
    return [entry, ...list.filter((item) => item.id !== entry.id)].slice(0, max);
}

/** Guest datasets are deleted by the server after a while, so stop listing the ones that are gone. */
export function pruneExpired(list: RecentDataset[], now: Date, retentionHours: number): RecentDataset[] {
    const cutoff = now.getTime() - retentionHours * 3_600_000;
    return list.filter((item) => {
        const savedAt = Date.parse(item.savedAt);
        return Number.isFinite(savedAt) && savedAt >= cutoff;
    });
}

export function removeRecent(list: RecentDataset[], id: string): RecentDataset[] {
    return list.filter((item) => item.id !== id);
}

function isRecent(value: unknown): value is RecentDataset {
    if (typeof value !== "object" || value === null) return false;
    const item = value as Record<string, unknown>;
    const nullableNumber = (v: unknown) => v === null || typeof v === "number";
    return (
        typeof item.id === "string" &&
        typeof item.name === "string" &&
        typeof item.fileName === "string" &&
        typeof item.savedAt === "string" &&
        nullableNumber(item.rows) &&
        nullableNumber(item.columns) &&
        nullableNumber(item.qualityScore)
    );
}

export function parseRecent(raw: string | null): RecentDataset[] {
    if (!raw) return [];
    try {
        const data: unknown = JSON.parse(raw);
        return Array.isArray(data) ? data.filter(isRecent).slice(0, MAX_RECENT) : [];
    } catch {
        return [];
    }
}

type ReadableStorage = Pick<Storage, "getItem">;
type WritableStorage = Pick<Storage, "setItem">;

export function loadRecent(storage?: ReadableStorage): RecentDataset[] {
    try {
        return parseRecent((storage ?? window.localStorage).getItem(RECENT_KEY));
    } catch {
        return [];
    }
}

export function saveRecent(list: RecentDataset[], storage?: WritableStorage): void {
    try {
        (storage ?? window.localStorage).setItem(RECENT_KEY, JSON.stringify(list.slice(0, MAX_RECENT)));
    } catch {
        // Storage can be unavailable (private mode, quota). Remembering datasets is a convenience only.
    }
}