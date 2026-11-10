import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import type { ReactNode } from "react";

import { SiteHeader } from "@/components/SideHeader";

import "./global.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jb-mono", display: "swap" });

export const metadata: Metadata = {
    title: { default: "Ledger: governed analytics", template: "%s \u00b7 Ledger" },
    description:
        "Define each business metric once, ask questions in plain English, and get answers computed from governed definitions.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
    return (
        <html lang="en" className={`${inter.variable} ${mono.variable}`}>
            <body className="min-h-dvh font-sans">
                <SiteHeader />
                {children}
                <footer className="mx-auto max-w-6xl px-4 pb-10 pt-4 text-xs text-slate-400 sm:px-6">
                    Metrics are defined once and versioned. The AI chooses a definition; it never writes the math.
                </footer>
            </body>
        </html>
    );
}