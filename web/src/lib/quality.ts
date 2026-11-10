import { NULL_PCT_IS_FRACTION } from "./config.ts";
import { dateOnly, formatNumber, formatPercent } from "./format.ts";
import type { ColumnProfile } from "./types.ts";

export type QualityTone = "excellent" | "good" | "attention" | "poor" | "unknown";

export interface QualityBand {
    label: string;
    tone: QualityTone;
}

export function qualityBand(score: number | null | undefined): QualityBand {
    if (score === null || score === undefined || Number.isNaN(score)) return { label: "Not scored", tone: "unknown" };
    if (score >= 90) return { label: "Excellent", tone: "excellent" };
    if (score >= 75) return { label: "Good", tone: "good" };
    if (score >= 50) return { label: "Needs attention", tone: "attention" };
    return { label: "Poor", tone: "poor" };
}

/** The share of missing values in a column, as a percentage from 0 to 100. */
export function nullPercent(column: Pick<ColumnProfile, "null_pct">): number {
    const raw = column.null_pct ?? 0;
    const percent = NULL_PCT_IS_FRACTION ? raw * 100 : raw;
    return Math.min(100, Math.max(0, percent));
}

/** Average completeness across columns, as a percentage. Null when there are no columns. */
export function completeness(columns: Pick<ColumnProfile, "null_pct">[]): number | null {
    if (columns.length === 0) return null;
    const missing = columns.reduce((sum, column) => sum + nullPercent(column), 0) / columns.length;
    return Math.round((100 - missing) * 10) / 10;
}

export type ColumnHealth = "complete" | "gaps" | "sparse";

export function columnHealth(column: Pick<ColumnProfile, "null_pct">): ColumnHealth {
    const missing = nullPercent(column);
    if (missing === 0) return "complete";
    return missing >= 20 ? "sparse" : "gaps";
}

export interface Finding {
    severity: "warning" | "info";
    column: string;
    message: string;
}

const IDENTIFIER_TYPES = new Set(["integer", "text"]);

/** Plain-language observations derived from the profile. Nothing here is estimated: it is all read off the numbers. */
export function findings(columns: ColumnProfile[], rowCount: number | null): Finding[] {
    const found: Finding[] = [];
    for (const column of columns) {
        const missing = nullPercent(column);
        if (missing >= 100) {
            found.push({ severity: "warning", column: column.name, message: "has no values at all" });
        } else if (missing > 0) {
            found.push({
                severity: missing >= 20 ? "warning" : "info",
                column: column.name,
                message: `is missing ${formatPercent(missing)} of its values`,
            });
        }
        if (rowCount !== null && rowCount > 1 && column.unique_count === 1 && missing < 100) {
            found.push({ severity: "info", column: column.name, message: "has the same value in every row" });
        }
        if (
            rowCount !== null &&
            rowCount >= 5 &&
            column.unique_count === rowCount &&
            missing === 0 &&
            IDENTIFIER_TYPES.has(column.dtype)
        ) {
            found.push({ severity: "info", column: column.name, message: "is unique in every row, so it looks like an identifier" });
        }
    }
    return found
        .map((item, index) => ({ item, index }))
        .sort((a, b) => (a.item.severity === b.item.severity ? a.index - b.index : a.item.severity === "warning" ? -1 : 1))
        .map(({ item }) => item);
}

/** A short description of what is in a column, for the table. */
export function statLine(column: ColumnProfile): string {
    const stats = column.stats;
    if (!stats) return "\u2014";
    if (column.dtype === "integer" || column.dtype === "float") {
        const parts: string[] = [];
        if (typeof stats.min === "number" && typeof stats.max === "number") {
            parts.push(`${formatNumber(stats.min)} \u2013 ${formatNumber(stats.max)}`);
        }
        if (typeof stats.mean === "number") parts.push(`mean ${formatNumber(stats.mean)}`);
        return parts.join(" \u00b7 ") || "\u2014";
    }
    if (column.dtype === "datetime") {
        if (typeof stats.min === "string" && typeof stats.max === "string") {
            return `${dateOnly(stats.min)} \u2192 ${dateOnly(stats.max)}`;
        }
        return "\u2014";
    }
    if (stats.top_values && stats.top_values.length > 0) {
        const names = stats.top_values.slice(0, 3).map((entry) => String(entry.value ?? "(blank)"));
        return names.join(", ") + (stats.top_values.length > 3 ? ", \u2026" : "");
    }
    return "\u2014";
}