export default function Loading() {
    return (
        <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6" aria-busy="true">
            <div className="h-3 w-32 animate-pulse rounded bg-slate-200" />
            <div className="mt-4 h-7 w-64 animate-pulse rounded bg-slate-200" />
            <div className="mt-8 grid grid-cols-2 gap-3 lg:grid-cols-4">
                {[0, 1, 2, 3].map((item) => (
                    <div key={item} className="h-24 animate-pulse rounded-xl border border-slate-200 bg-white" />
                ))}
            </div>
            <div className="mt-6 grid gap-4 lg:grid-cols-3">
                <div className="h-44 animate-pulse rounded-xl border border-slate-200 bg-white" />
                <div className="h-44 animate-pulse rounded-xl border border-slate-200 bg-white lg:col-span-2" />
            </div>
            <p className="mt-6 text-center text-xs text-slate-500" role="status">
                Loading your dataset. The first request can take up to a minute while the service wakes up.
            </p>
        </main>
    );
}