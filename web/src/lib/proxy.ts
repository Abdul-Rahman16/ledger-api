// Pure helpers for the server-side proxy in app/api/ledger/[...path]/route.ts.
// The browser never talks to the Ledger API directly, and it never supplies identity:
// the proxy builds the upstream headers itself.

const UUID = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
const METRIC = "[a-z][a-z0-9_]{1,59}";

const GET = ["GET"];
const POST = ["POST"];

/** Only these API routes can be reached from the browser. /internal/* is deliberately absent. */
const ROUTES: Array<[RegExp, string[]]> = [
    [/^health$/, GET],
    [/^datasets$/, ["GET", "POST"]],
    [new RegExp(`^datasets/${UUID}$`), GET],
    [new RegExp(`^datasets/${UUID}/metrics$`), ["GET", "POST"]],
    [new RegExp(`^datasets/${UUID}/metrics/validate$`), POST],
    [new RegExp(`^datasets/${UUID}/metrics/${METRIC}$`), ["GET", "DELETE"]],
    [new RegExp(`^datasets/${UUID}/metrics/${METRIC}/versions$`), ["GET", "POST"]],
    [new RegExp(`^datasets/${UUID}/query$`), POST],
    [new RegExp(`^datasets/${UUID}/ask$`), POST],
    [new RegExp(`^datasets/${UUID}/pipeline$`), GET],
];

export function isAllowedRequest(method: string, segments: string[]): boolean {
    if (segments.length === 0) return false;
    if (segments.some((segment) => segment === "" || segment === "." || segment === ".." || /[\\%?#\s]/.test(segment))) {
        return false;
    }
    const path = segments.join("/");
    const verb = method.toUpperCase();
    return ROUTES.some(([pattern, methods]) => pattern.test(path) && methods.includes(verb));
}

export function isUuid(value: string): boolean {
    return new RegExp(`^${UUID}$`).test(value);
}

export function upstreamUrl(base: string, segments: string[], search: string): string {
    const query = search && search.length <= 200 ? search : "";
    return `${base.replace(/\/+$/, "")}/${segments.join("/")}${query}`;
}

/** The first address in X-Forwarded-For (or X-Real-IP), if it looks like an IP address. */
export function clientIpFrom(headers: Headers): string | null {
    const candidate = (headers.get("x-forwarded-for")?.split(",")[0] ?? headers.get("x-real-ip") ?? "").trim();
    return /^[0-9a-fA-F:.]{3,45}$/.test(candidate) ? candidate : null;
}

/**
 * Upstream request headers. Only content-type and accept are copied from the browser;
 * x-user-id, x-internal-secret, cookies and everything else are dropped.
 */
export function buildUpstreamHeaders(
    incoming: Headers,
    identity: Record<string, string>,
    clientIp: string | null,
): Headers {
    const headers = new Headers();
    for (const name of ["content-type", "accept"]) {
        const value = incoming.get(name);
        if (value) headers.set(name, value);
    }
    for (const [name, value] of Object.entries(identity)) headers.set(name, value);
    if (clientIp) headers.set("x-forwarded-for", clientIp);
    return headers;
}

export function pickResponseHeaders(upstream: Headers): Headers {
    const headers = new Headers();
    for (const name of ["content-type", "retry-after"]) {
        const value = upstream.get(name);
        if (value) headers.set(name, value);
    }
    return headers;
}