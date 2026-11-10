"use client";

import Link from "next/link";

export default function DatasetError({ reset }: { error: Error; reset: () => void }) {
    return (
        <main className="mx-auto max-w-xl px-4 py-24 text-center sm:px-6">
            <h1 className="text-xl font-semibold text-slate-900">We couldn&rsquo;t load this dataset</h1>
            <p className="mt-2 text-sm text-slate-600">
                The service may be waking up or briefly unavailable. Give it a few seconds and try again.
            </p>
            <div className="mt-6 flex items-center justify-center gap-3">
                <button
                    type="button"
                    onClick={reset}
                    className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-500"
                >
                    Try again
                </button>
                <Link href="/" className="text-sm font-medium text-slate-600 hover:text-slate-900">
                    Back to upload
                </Link>
            </div>
        </main>
    );
}