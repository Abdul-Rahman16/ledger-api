import "server-only";

import { cache } from "react";

import { isUuid } from "./proxy.ts";
import type { DatasetDetail } from "./types.ts";

export const LEDGER_API_URL = (process.env.LEDGER_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

const REQUEST_TIMEOUT_MS = 55_000;

export interface Identity {
    /** null means a guest: no identity headers are sent and nothing is saved to an account. */
    userId: string | null;
}

/**
 * Who is making this request. Guest mode only for now.
 * When sign-in is added, read the NextAuth session here and return its user id. This is the only place
 * that has to change: the proxy route and every server component already go through it.
 */
export async function currentIdentity(): Promise<Identity> {
    return { userId: null };
}

/** Server-side identity headers. The shared secret never leaves the server. */
export function identityHeaders(identity: Identity): Record<string, string> {
    if (!identity.userId) return {};
    const secret = process.env.LEDGER_INTERNAL_SECRET;
    if (!secret) throw new Error("LEDGER_INTERNAL_SECRET is not set");
    return { "X-User-Id": identity.userId, "X-Internal-Secret": secret };
}

export async function ledgerFetch(path: string, init: RequestInit = {}): Promise<Response> {
    const identity = await currentIdentity();
    const headers = new Headers(init.headers);
    for (const [name, value] of Object.entries(identityHeaders(identity))) headers.set(name, value);
    return fetch(`${LEDGER_API_URL}${path}`, {
        ...init,
        headers,
        cache: "no-store",
        signal: init.signal ?? AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
}

/** One fetch per request, even when both the page and its metadata ask for the dataset. */
export const getDataset = cache(async (id: string): Promise<DatasetDetail | null> => {
    if (!isUuid(id)) return null;
    const response = await ledgerFetch(`/datasets/${id}`);
    if (response.status === 404) return null;
    if (!response.ok) throw new Error(`The Ledger API returned ${response.status}`);
    return (await response.json()) as DatasetDetail;
});