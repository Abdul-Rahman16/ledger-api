import Link from "next/link";

import { GUEST_RETENTION_HOURS } from "@/lib/config";

function LogoMark() {
    return (
        <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
            <rect width="26" height="26" rx="7" className="fill-indigo-600" />
            <rect x="6" y="13" width="3.2" height="7" rx="1" fill="white" opacity="0.85" />
            <rect x="11.4" y="9" width="3.2" height="11" rx="1" fill="white" />
            <rect x="16.8" y="6" width="3.2" height="14" rx="1" fill="white" opacity="0.85" />
        </svg>
    );
}

export function SiteHeader() {
    return (
        <header className="sticky top-0 z-30 border-b border-slate-200/70 bg-white/80 backdrop-blur">
            <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:px-6">
                <Link href="/" className="flex items-center gap-2.5 rounded-md outline-offset-4">
                    <LogoMark />
                    <span className="text-[15px] font-semibold tracking-tight text-slate-900">Ledger</span>
                    <span className="hidden rounded-full border border-slate-200 px-2 py-0.5 text-xs font-medium text-slate-500 sm:inline">
                        Governed analytics
                    </span>
                </Link>
                <span
                    className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600"
                    title={`Guest datasets are deleted after ${GUEST_RETENTION_HOURS} hours`}
                >
                    <span className="size-1.5 rounded-full bg-emerald-500" />
                    Guest mode
                </span>
            </div>
        </header>
    );
}