const numberFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

export function formatNumber(value: number | null | undefined, maxFractionDigits = 2): string {
    if (value === null || value === undefined || Number.isNaN(value)) return "\u2014";
    if (maxFractionDigits === 2) return numberFormat.format(value);
    return new Intl.NumberFormat("en-US", { maximumFractionDigits: maxFractionDigits }).format(value);
}

export function formatBytes(bytes: number): string {
    if (!Number.isFinite(bytes) || bytes < 0) return "\u2014";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
    if (value === null || value === undefined || Number.isNaN(value)) return "\u2014";
    const rounded = Number(value.toFixed(digits));
    return `${rounded}%`;
}

/** The API sends UTC timestamps without a zone suffix. Parse them as UTC, not local time. */
export function parseApiDate(value: string): Date {
    const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
    return new Date(hasZone ? value : `${value}Z`);
}

export function timeAgo(date: Date, now: Date = new Date()): string {
    const seconds = Math.round((now.getTime() - date.getTime()) / 1000);
    if (Number.isNaN(seconds)) return "";
    if (seconds < 45) return "just now";
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes} min ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours} h ago`;
    const days = Math.round(hours / 24);
    return `${days} d ago`;
}

export function truncate(text: string, max: number): string {
    return text.length <= max ? text : `${text.slice(0, Math.max(0, max - 1))}\u2026`;
}

export function humanizeDtype(dtype: string): string {
    switch (dtype) {
        case "integer":
            return "Integer";
        case "float":
            return "Decimal";
        case "text":
            return "Text";
        case "datetime":
            return "Date/time";
        default:
            return dtype.charAt(0).toUpperCase() + dtype.slice(1);
    }
}

/** "2026-01-05T00:00:00" -> "2026-01-05" */
export function dateOnly(value: string): string {
    return value.slice(0, 10);
}

/** Whole hours left before a guest dataset is deleted, rounded up and never below zero. */
export function hoursLeft(createdAt: Date, retentionHours: number, now: Date = new Date()): number {
    const remaining = createdAt.getTime() + retentionHours * 3_600_000 - now.getTime();
    return Number.isFinite(remaining) ? Math.max(0, Math.ceil(remaining / 3_600_000)) : 0;
}