import Link from "next/link";

import { GUEST_RETENTION_HOURS } from "@/lib/config";

export default function NotFound() {
    return (
        <main className="mx-auto max-w-xl px-4 py-24 text-center sm:px-6">
            <h1 className="text-xl font-semibold text-slate-900">Dataset not found</h1>
            <p className="mt-2 text-sm text-slate-600">
                The link may be wrong, or the dataset has been deleted. Guest datasets are removed automatically after{" "}
                {GUEST_RETENTION_HOURS} hours.
            </p>
            <Link
                href="/"
                className="mt-6 inline-block rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-500"
            >
                Upload a dataset
            </Link>
        </main>
    );
}