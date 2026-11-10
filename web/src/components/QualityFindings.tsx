import type { Finding } from "@/lib/quality";

export function QualityFindings({ items }: { items: Finding[] }) {
    if (items.length === 0) {
        return (
            <div className="flex items-start gap-3 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800 ring-1 ring-emerald-200">
                <svg viewBox="0 0 20 20" className="mt-0.5 size-4 shrink-0" fill="currentColor" aria-hidden="true">
                    <path d="M10 2a8 8 0 1 0 0 16 8 8 0 0 0 0-16Zm-1 11.2L5.8 10l1.1-1.1L9 11l4.1-4.1 1.1 1.1L9 13.2Z" />
                </svg>
                <p>No issues found. Every column is complete and nothing looks suspicious.</p>
            </div>
        );
    }

    return (
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
            {items.map((item, index) => (
                <li key={`${item.column}-${index}`} className="flex items-start gap-3 px-4 py-3 text-sm">
                    <span
                        className={`mt-1.5 size-2 shrink-0 rounded-full ${item.severity === "warning" ? "bg-amber-500" : "bg-slate-300"}`}
                        aria-label={item.severity === "warning" ? "Warning" : "Note"}
                    />
                    <p className="text-slate-700">
                        <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[12.5px] text-slate-900">{item.column}</code>{" "}
                        {item.message}.
                    </p>
                </li>
            ))}
        </ul>
    );
}