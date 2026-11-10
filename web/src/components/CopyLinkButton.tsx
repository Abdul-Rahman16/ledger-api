"use client";

import { useState } from "react";

export function CopyLinkButton() {
    const [copied, setCopied] = useState(false);

    async function copy() {
        try {
            await navigator.clipboard.writeText(window.location.href);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 2000);
        } catch {
            // Clipboard access can be blocked; the address bar still has the link.
        }
    }

    return (
        <button
            type="button"
            onClick={() => void copy()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm transition hover:border-indigo-300 hover:text-indigo-700"
        >
            <svg viewBox="0 0 20 20" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M8 12a3 3 0 0 0 4.2 0l3-3a3 3 0 0 0-4.2-4.2l-.7.7M12 8a3 3 0 0 0-4.2 0l-3 3A3 3 0 0 0 9 15.2l.7-.7" />
            </svg>
            <span aria-live="polite">{copied ? "Link copied" : "Copy link"}</span>
        </button>
    );
}