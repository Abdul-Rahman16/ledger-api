import { humanizeDtype } from "@/lib/format";

const STYLES: Record<string, string> = {
    integer: "bg-sky-50 text-sky-700 ring-sky-200",
    float: "bg-sky-50 text-sky-700 ring-sky-200",
    text: "bg-slate-100 text-slate-700 ring-slate-200",
    datetime: "bg-violet-50 text-violet-700 ring-violet-200",
};

export function TypeBadge({ dtype }: { dtype: string }) {
    return (
        <span
            className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${STYLES[dtype] ?? "bg-slate-100 text-slate-700 ring-slate-200"
                }`}
        >
            {humanizeDtype(dtype)}
        </span>
    );
}