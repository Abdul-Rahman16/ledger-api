import { RecentDatasets } from "@/components/RecentDatasets";
import { UploadCard } from "@/components/UploadCard";
import { WarmUp } from "@/components/WarmUp";

const STEPS = [
    {
        title: "Upload and profile",
        body: "Drop in a CSV, Excel or JSON file. Ledger detects column types, counts missing values and scores data quality in seconds.",
    },
    {
        title: "Define metrics once",
        body: "Revenue, order count, average order value: each is a versioned definition with a validated formula, not a prompt.",
    },
    {
        title: "Ask in plain English",
        body: "Your question is matched to a governed metric, run read-only, and explained using only numbers from the result.",
    },
];

export default function HomePage() {
    return (
        <main className="mx-auto max-w-6xl px-4 pb-16 pt-12 sm:px-6 sm:pt-16">
            <WarmUp />
            <div className="mx-auto max-w-3xl text-center">
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-indigo-600">Governed analytics</p>
                <h1 className="mt-3 text-balance text-4xl font-semibold tracking-tight text-slate-900 sm:text-5xl">
                    Ask questions of your data. Get answers you can trust.
                </h1>
                <p className="mx-auto mt-4 max-w-2xl text-pretty text-base leading-relaxed text-slate-600 sm:text-lg">
                    Metrics get explicit, versioned definitions. Ledger resolves your question to one of them, runs a read-only
                    query and explains the result. The AI never invents the math.
                </p>
            </div>

            <div className="mx-auto mt-10 max-w-2xl">
                <UploadCard />
            </div>

            <RecentDatasets />

            <section aria-labelledby="how-heading" className="mt-16">
                <h2 id="how-heading" className="text-sm font-semibold text-slate-900">
                    How it works
                </h2>
                <ol className="mt-4 grid gap-4 md:grid-cols-3">
                    {STEPS.map((step, index) => (
                        <li key={step.title} className="rounded-xl border border-slate-200 bg-white p-5">
                            <span className="flex size-7 items-center justify-center rounded-full bg-indigo-50 text-xs font-semibold text-indigo-700">
                                {index + 1}
                            </span>
                            <h3 className="mt-3 text-sm font-semibold text-slate-900">{step.title}</h3>
                            <p className="mt-1.5 text-sm leading-relaxed text-slate-600">{step.body}</p>
                        </li>
                    ))}
                </ol>
            </section>
        </main>
    );
}