"use client";

import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { dateOnly, formatNumber, formatPercent, truncate } from "@/lib/format";
import { columnHealth, nullPercent, statLine } from "@/lib/quality";
import type { ColumnProfile } from "@/lib/types";

import { TypeBadge } from "./TypeBadge";

const HEALTH_BAR = { complete: "bg-emerald-500", gaps: "bg-amber-400", sparse: "bg-amber-500" } as const;

function hasDetails(column: ColumnProfile): boolean {
    const stats = column.stats;
    if (!stats) return false;
    return Boolean(stats.top_values?.length) || stats.min !== undefined || stats.mean !== undefined;
}

function Detail({ column }: { column: ColumnProfile }) {
    const stats = column.stats;
    if (!stats) return null;

    if (stats.top_values && stats.top_values.length > 0) {
        const data = stats.top_values.map((entry) => ({
            label: truncate(String(entry.value ?? "(blank)"), 22),
            count: entry.count,
        }));
        return (
            <div>
                <p className="mb-2 text-xs font-medium text-slate-500">Most common values</p>
                <div style={{ height: Math.max(120, data.length * 30 + 16) }} className="w-full max-w-xl">
                    <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 0 }}>
                            <XAxis type="number" hide />
                            <YAxis type="category" dataKey="label" width={120} tick={{ fontSize: 12, fill: "#334155" }} axisLine={false} tickLine={false} />
                            <Tooltip cursor={{ fill: "#f1f5f9" }} formatter={(value) => [value, "Rows"]} />
                            <Bar dataKey="count" fill="#818cf8" radius={[0, 6, 6, 0]} barSize={14} />
                        </BarChart>
                    </ResponsiveContainer>
                </div>
            </div>
        );
    }

    const isDate = column.dtype === "datetime";
    const items: Array<[string, string]> = [];
    if (stats.min !== undefined && stats.min !== null) {
        items.push([isDate ? "Earliest" : "Minimum", isDate ? dateOnly(String(stats.min)) : formatNumber(Number(stats.min))]);
    }
    if (typeof stats.mean === "number") items.push(["Average", formatNumber(stats.mean)]);
    if (stats.max !== undefined && stats.max !== null) {
        items.push([isDate ? "Latest" : "Maximum", isDate ? dateOnly(String(stats.max)) : formatNumber(Number(stats.max))]);
    }
    return (
        <dl className="grid max-w-md grid-cols-3 gap-4">
            {items.map(([label, value]) => (
                <div key={label}>
                    <dt className="text-xs font-medium text-slate-500">{label}</dt>
                    <dd className="mt-1 text-sm font-semibold tabular-nums text-slate-900">{value}</dd>
                </div>
            ))}
        </dl>
    );
}

export function ColumnTable({ columns, rowCount }: { columns: ColumnProfile[]; rowCount: number | null }) {
    const [query, setQuery] = useState("");
    const [open, setOpen] = useState<string | null>(null);

    const visible = useMemo(() => {
        const needle = query.trim().toLowerCase();
        return needle ? columns.filter((column) => column.name.toLowerCase().includes(needle)) : columns;
    }, [columns, query]);

    return (
        <div className="rounded-xl border border-slate-200 bg-white">
            <div className="flex flex-col gap-3 border-b border-slate-100 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
                <h2 className="text-sm font-semibold text-slate-900">
                    Columns <span className="ml-1 font-normal text-slate-400">{columns.length}</span>
                </h2>
                {columns.length > 8 ? (
                    <input
                        type="search"
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        placeholder="Filter columns"
                        aria-label="Filter columns"
                        className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-sm outline-none transition focus:border-indigo-400 focus:bg-white sm:w-56"
                    />
                ) : null}
            </div>

            <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] text-left text-sm">
                    <thead>
                        <tr className="text-xs font-medium text-slate-500">
                            <th scope="col" className="px-4 py-2.5 sm:px-5">Column</th>
                            <th scope="col" className="px-3 py-2.5">Type</th>
                            <th scope="col" className="px-3 py-2.5">Completeness</th>
                            <th scope="col" className="px-3 py-2.5 text-right">Distinct</th>
                            <th scope="col" className="px-4 py-2.5 sm:px-5">Contents</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                        {visible.map((column) => {
                            const complete = 100 - nullPercent(column);
                            const expandable = hasDetails(column);
                            const isOpen = open === column.name;
                            return (
                                <ColumnRow
                                    key={column.name}
                                    column={column}
                                    complete={complete}
                                    expandable={expandable}
                                    isOpen={isOpen}
                                    onToggle={() => setOpen(isOpen ? null : column.name)}
                                    rowCount={rowCount}
                                />
                            );
                        })}
                        {visible.length === 0 ? (
                            <tr>
                                <td colSpan={5} className="px-5 py-8 text-center text-sm text-slate-500">
                                    No columns match &ldquo;{query}&rdquo;.
                                </td>
                            </tr>
                        ) : null}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

function ColumnRow({
    column,
    complete,
    expandable,
    isOpen,
    onToggle,
    rowCount,
}: {
    column: ColumnProfile;
    complete: number;
    expandable: boolean;
    isOpen: boolean;
    onToggle: () => void;
    rowCount: number | null;
}) {
    return (
        <>
            <tr className={expandable ? "cursor-pointer transition hover:bg-slate-50/70" : ""} onClick={expandable ? onToggle : undefined}>
                <td className="px-4 py-3 sm:px-5">
                    <span className="flex items-center gap-2">
                        {expandable ? (
                            <svg viewBox="0 0 20 20" className={`size-3.5 shrink-0 text-slate-400 transition-transform ${isOpen ? "rotate-90" : ""}`} fill="currentColor" aria-hidden="true">
                                <path d="m7 4.5 6 5.5-6 5.5V4.5Z" />
                            </svg>
                        ) : (
                            <span className="size-3.5 shrink-0" />
                        )}
                        <code className="font-mono text-[13px] font-medium text-slate-900">{column.name}</code>
                    </span>
                </td>
                <td className="px-3 py-3"><TypeBadge dtype={column.dtype} /></td>
                <td className="px-3 py-3">
                    <span className="flex items-center gap-2.5">
                        <span className="h-1.5 w-20 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
                            <span className={`block h-full rounded-full ${HEALTH_BAR[columnHealth(column)]}`} style={{ width: `${complete}%` }} />
                        </span>
                        <span className="text-xs tabular-nums text-slate-600">{formatPercent(complete)}</span>
                    </span>
                </td>
                <td className="px-3 py-3 text-right tabular-nums text-slate-700">
                    {column.unique_count === null ? "\u2014" : formatNumber(column.unique_count, 0)}
                    {rowCount && column.unique_count === rowCount ? <span className="ml-1.5 text-[11px] text-slate-400">all unique</span> : null}
                </td>
                <td className="max-w-xs truncate px-4 py-3 text-slate-600 sm:px-5">{statLine(column)}</td>
            </tr>
            <AnimatePresence initial={false}>
                {expandable && isOpen ? (
                    <tr>
                        <td colSpan={5} className="bg-slate-50/60 p-0">
                            <motion.div
                                initial={{ height: 0, opacity: 0 }}
                                animate={{ height: "auto", opacity: 1 }}
                                exit={{ height: 0, opacity: 0 }}
                                transition={{ duration: 0.2, ease: "easeOut" }}
                                className="overflow-hidden"
                            >
                                <div className="px-5 py-4 sm:px-9">
                                    <Detail column={column} />
                                </div>
                            </motion.div>
                        </td>
                    </tr>
                ) : null}
            </AnimatePresence>
        </>
    );
}