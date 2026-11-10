"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { GUEST_RETENTION_HOURS } from "@/lib/config";
import { formatNumber, timeAgo } from "@/lib/format";
import { qualityBand } from "@/lib/quality";
import { loadRecent, pruneExpired, removeRecent, saveRecent, type RecentDataset } from "@/lib/recent";

const TONE_DOT: Record<string, string> = {
    excellent: "bg-emerald-500",
    good: "bg-emerald-400",
    attention: "bg-amber-500",
    poor: "bg-rose-500",
    unknown: "bg-slate-300",
};

export function RecentDatasets() {
    const [items, setItems] = useState<RecentDataset[]>([]);

    useEffect(() => {
        const live = pruneExpired(loadRecent(), new Date(), GUEST_RETENTION_HOURS);
        saveRecent(live);
        setItems(live);
    }, []);

    if (items.length === 0) return null;

    return (
        <section aria-labelledby="recent-heading" className="mt-14">
            <h2 id="recent-heading" className="text-sm font-semibold text-slate-900">
                Your recent datasets
            </h2>
            <p className="mt-1 text-xs text-slate-500">Saved in this browser only. They disappear when the server deletes them.</p>
            <ul className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {items.map((item) => {
                    const band = qualityBand(item.qualityScore);
                    return (
                        <li key={item.id} className="group relative rounded-xl border border-slate-200 bg-white p-4 transition hover:border-indigo-300 hover:shadow-sm">
                            <Link href={`/d/${item.id}`} className="block rounded-md outline-offset-4">
                                <p className="truncate text-sm font-semibold text-slate-900">{item.name}</p>
                                <p className="mt-0.5 truncate text-xs text-slate-500">{item.fileName}</p>
                                <p className="mt-3 flex items-center gap-2 text-xs text-slate-600">
                                    <span className={`size-2 rounded-full ${TONE_DOT[band.tone]}`} aria-hidden="true" />
                                    {item.rows !== null ? `${formatNumber(item.rows, 0)} rows` : "Rows unknown"}
                                    {item.columns !== null ? ` · ${item.columns} columns` : ""}
                                    <span className="ml-auto text-slate-400">{timeAgo(new Date(item.savedAt))}</span>
                                </p>
                            </Link>
                            <button
                                type="button"
                                aria-label={`Remove ${item.name} from this list`}
                                onClick={() => {
                                    const next = removeRecent(items, item.id);
                                    saveRecent(next);
                                    setItems(next);
                                }}
                                className="absolute right-2 top-2 rounded-md p-1 text-slate-300 opacity-0 transition hover:bg-slate-100 hover:text-slate-600 focus:opacity-100 group-hover:opacity-100"
                            >
                                <svg viewBox="0 0 20 20" className="size-4" fill="currentColor" aria-hidden="true">
                                    <path d="m6.3 5.2 3.7 3.7 3.7-3.7 1.1 1.1-3.7 3.7 3.7 3.7-1.1 1.1-3.7-3.7-3.7 3.7-1.1-1.1L8.9 10 5.2 6.3l1.1-1.1Z" />
                                </svg>
                            </button>
                        </li>
                    );
                })}
            </ul>
        </section>
    );
}