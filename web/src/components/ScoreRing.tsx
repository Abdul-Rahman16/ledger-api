"use client";

import { motion } from "motion/react";

import type { QualityTone } from "@/lib/quality";

const TONE_STROKE: Record<QualityTone, string> = {
    excellent: "stroke-emerald-500",
    good: "stroke-emerald-400",
    attention: "stroke-amber-500",
    poor: "stroke-rose-500",
    unknown: "stroke-slate-300",
};

export function ScoreRing({ score, tone, size = 132 }: { score: number | null; tone: QualityTone; size?: number }) {
    const strokeWidth = 10;
    const radius = (size - strokeWidth) / 2;
    const circumference = 2 * Math.PI * radius;
    const fraction = score === null ? 0 : Math.min(1, Math.max(0, score / 100));

    return (
        <div className="relative shrink-0" style={{ width: size, height: size }}>
            <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90" aria-hidden="true">
                <circle cx={size / 2} cy={size / 2} r={radius} fill="none" strokeWidth={strokeWidth} className="stroke-slate-100" />
                <motion.circle
                    cx={size / 2}
                    cy={size / 2}
                    r={radius}
                    fill="none"
                    strokeWidth={strokeWidth}
                    strokeLinecap="round"
                    className={TONE_STROKE[tone]}
                    strokeDasharray={circumference}
                    initial={{ strokeDashoffset: circumference }}
                    animate={{ strokeDashoffset: circumference * (1 - fraction) }}
                    transition={{ duration: 1, ease: "easeOut" }}
                />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-3xl font-semibold tabular-nums tracking-tight text-slate-900">
                    {score === null ? "\u2014" : Math.round(score)}
                </span>
                <span className="text-[11px] font-medium uppercase tracking-wide text-slate-400">out of 100</span>
            </div>
        </div>
    );
}