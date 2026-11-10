import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ColumnTable } from "@/components/ColumnTable";
import { CopyLinkButton } from "@/components/CopyLinkButton";
import { MissingValuesChart } from "@/components/MissingValueChart";
import { QualityFindings } from "@/components/QualityFindings";
import { ScoreRing } from "@/components/ScoreRing";
import { StatCard } from "@/components/StatCard";
import { GUEST_RETENTION_HOURS } from "@/lib/config";
import { formatNumber, formatPercent, hoursLeft, parseApiDate, timeAgo } from "@/lib/format";
import { getDataset } from "@/lib/ledger-server";
import { completeness, findings, qualityBand } from "@/lib/quality";

type PageProps = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
    const { id } = await params;
    const dataset = await getDataset(id).catch(() => null);
    return { title: dataset ? dataset.name : "Dataset" };
}

export default async function DatasetPage({ params }: PageProps) {
    const { id } = await params;
    const dataset = await getDataset(id);
    if (!dataset) notFound();

    const band = qualityBand(dataset.quality_score);
    const filled = completeness(dataset.columns);
    const items = findings(dataset.columns, dataset.row_count);
    const created = parseApiDate(dataset.created_at);
    const remaining = hoursLeft(created, GUEST_RETENTION_HOURS);

    return (
        <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
            <nav aria-label="Breadcrumb" className="text-xs text-slate-500">
                <Link href="/" className="hover:text-slate-800">
                    Datasets
                </Link>
                <span className="mx-1.5 text-slate-300">/</span>
                <span className="text-slate-700">{dataset.name}</span>
            </nav>

            <header className="mt-3 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                    <h1 className="truncate text-2xl font-semibold tracking-tight text-slate-900">{dataset.name}</h1>
                    <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-slate-500">
                        <span className="font-mono text-[13px]">{dataset.original_filename}</span>
                        <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-200">
                            <span className="size-1.5 rounded-full bg-emerald-500" />
                            {dataset.status === "ready" ? "Ready" : dataset.status}
                        </span>
                        <time dateTime={created.toISOString()}>Uploaded {timeAgo(created)}</time>
                    </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                    <CopyLinkButton />
                    <Link
                        href="/"
                        className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm transition hover:bg-indigo-500"
                    >
                        Upload another
                    </Link>
                </div>
            </header>

            <p className="mt-5 rounded-lg bg-amber-50 px-4 py-2.5 text-xs text-amber-900 ring-1 ring-amber-200">
                Guest dataset: anyone with this link can view it. It is deleted automatically in about {remaining}{" "}
                {remaining === 1 ? "hour" : "hours"}.
            </p>

            <section aria-label="Summary" className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
                <StatCard label="Rows" value={formatNumber(dataset.row_count, 0)} />
                <StatCard label="Columns" value={formatNumber(dataset.column_count, 0)} />
                <StatCard label="Completeness" value={formatPercent(filled)} hint="Average share of values present" />
                <StatCard label="Status" value={dataset.status === "ready" ? "Ready" : dataset.status} hint="Profiled on upload" />
            </section>

            <section aria-labelledby="quality-heading" className="mt-8">
                <h2 id="quality-heading" className="text-sm font-semibold text-slate-900">
                    Data quality
                </h2>
                <div className="mt-3 grid gap-4 lg:grid-cols-3">
                    <div className="flex items-center gap-5 rounded-xl border border-slate-200 bg-white p-5">
                        <ScoreRing score={dataset.quality_score} tone={band.tone} />
                        <div>
                            <p className="text-base font-semibold text-slate-900">{band.label}</p>
                            <p className="mt-1 text-xs leading-relaxed text-slate-500">
                                Based on missing values and duplicate rows removed during upload.
                            </p>
                        </div>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-white p-5 lg:col-span-2">
                        <h3 className="text-xs font-medium text-slate-500">Missing values by column</h3>
                        <div className="mt-3">
                            <MissingValuesChart columns={dataset.columns} />
                        </div>
                    </div>
                </div>

                <h3 className="mb-3 mt-6 text-xs font-medium text-slate-500">What we noticed</h3>
                <QualityFindings items={items} />
            </section>

            <section aria-labelledby="columns-heading" className="mt-8">
                <h2 id="columns-heading" className="sr-only">
                    Columns
                </h2>
                <ColumnTable columns={dataset.columns} rowCount={dataset.row_count} />
            </section>
        </main>
    );
}