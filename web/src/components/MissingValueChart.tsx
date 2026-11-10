"use client";

import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { nullPercent } from "@/lib/quality";
import type { ColumnProfile } from "@/lib/types";

export function MissingValuesChart({ columns }: { columns: ColumnProfile[] }) {
    const data = columns.map((column) => ({ name: column.name, missing: Number(nullPercent(column).toFixed(1)) }));
    const hasGaps = data.some((entry) => entry.missing > 0);

    if (!hasGaps) {
        return (
            <div className="flex h-full min-h-40 flex-col items-center justify-center rounded-lg bg-slate-50 px-6 py-8 text-center">
                <span className="flex size-10 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
                    <svg viewBox="0 0 20 20" className="size-5" fill="currentColor" aria-hidden="true">
                        <path d="M8.2 13.6 4.9 10.3l1.1-1.1 2.2 2.2 5.8-5.8 1.1 1.1-6.9 6.9Z" />
                    </svg>
                </span>
                <p className="mt-3 text-sm font-medium text-slate-900">No missing values</p>
                <p className="mt-1 text-xs text-slate-500">All {columns.length} columns are fully populated.</p>
            </div>
        );
    }

    return (
        <div style={{ height: Math.max(180, data.length * 34 + 24) }} className="w-full">
            <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }}>
                    <CartesianGrid horizontal={false} stroke="#e2e8f0" strokeDasharray="3 3" />
                    <XAxis
                        type="number"
                        domain={[0, 100]}
                        tickFormatter={(value) => `${value}%`}
                        tick={{ fontSize: 11, fill: "#64748b" }}
                        axisLine={false}
                        tickLine={false}
                    />
                    <YAxis
                        type="category"
                        dataKey="name"
                        width={112}
                        tick={{ fontSize: 12, fill: "#334155" }}
                        axisLine={false}
                        tickLine={false}
                    />
                    <Tooltip cursor={{ fill: "#f1f5f9" }} formatter={(value) => [`${value}%`, "Missing"]} />
                    <Bar dataKey="missing" radius={[0, 6, 6, 0]} barSize={14}>
                        {data.map((entry) => (
                            <Cell key={entry.name} fill={entry.missing >= 20 ? "#f59e0b" : entry.missing > 0 ? "#fbbf24" : "#e2e8f0"} />
                        ))}
                    </Bar>
                </BarChart>
            </ResponsiveContainer>
        </div>
    );
}