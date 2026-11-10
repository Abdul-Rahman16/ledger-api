import { NextRequest, NextResponse } from "next/server";

import { currentIdentity, identityHeaders, LEDGER_API_URL } from "@/lib/ledger-server";
import {
    buildUpstreamHeaders,
    clientIpFrom,
    isAllowedRequest,
    pickResponseHeaders,
    upstreamUrl,
} from "@/lib/proxy";

// The browser talks only to this route. It forwards a fixed list of API routes, builds the identity
// headers itself, and never exposes the API's internal endpoints or the shared secret.

export const dynamic = "force-dynamic";
export const maxDuration = 60; // the API can take a while to wake up on a free plan

// Vercel functions reject request bodies above 4.5 MB.
const MAX_BODY_BYTES = 4_500_000;
const UPSTREAM_TIMEOUT_MS = 55_000;

type RouteContext = { params: Promise<{ path: string[] }> };

function problem(detail: string, status: number): NextResponse {
    return NextResponse.json({ detail }, { status });
}

async function handle(request: NextRequest, context: RouteContext): Promise<NextResponse> {
    const { path } = await context.params;
    if (!isAllowedRequest(request.method, path)) return problem("Not found.", 404);

    const declared = Number(request.headers.get("content-length") ?? "0");
    if (declared > MAX_BODY_BYTES) return problem("The request is too large.", 413);

    const hasBody = request.method !== "GET" && request.method !== "HEAD";
    const body = hasBody ? await request.arrayBuffer() : undefined;
    if (body && body.byteLength > MAX_BODY_BYTES) return problem("The request is too large.", 413);

    const identity = await currentIdentity();
    const headers = buildUpstreamHeaders(request.headers, identityHeaders(identity), clientIpFrom(request.headers));
    const url = upstreamUrl(LEDGER_API_URL, path, request.nextUrl.search);

    try {
        const upstream = await fetch(url, {
            method: request.method,
            headers,
            body,
            cache: "no-store",
            signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
        });
        return new NextResponse(upstream.body, { status: upstream.status, headers: pickResponseHeaders(upstream.headers) });
    } catch (error) {
        const timedOut = error instanceof Error && (error.name === "TimeoutError" || error.name === "AbortError");
        return timedOut
            ? problem("The API took too long to respond. It may be waking up, so try again in a moment.", 504)
            : problem("Could not reach the API.", 502);
    }
}

export { handle as GET, handle as POST, handle as DELETE };