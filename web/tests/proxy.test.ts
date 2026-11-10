import assert from "node:assert/strict";
import { test } from "node:test";

import {
    buildUpstreamHeaders,
    clientIpFrom,
    isAllowedRequest,
    isUuid,
    pickResponseHeaders,
    upstreamUrl,
} from "../src/lib/proxy.ts";

const ID = "c56d392e-99ea-4ecd-9e51-2fd71aff8740";

function allowed(method: string, path: string): boolean {
    return isAllowedRequest(method, path.split("/"));
}

test("the public API routes are reachable with the right methods", () => {
    assert.ok(allowed("GET", "health"));
    assert.ok(allowed("POST", "datasets"));
    assert.ok(allowed("GET", "datasets"));
    assert.ok(allowed("GET", `datasets/${ID}`));
    assert.ok(allowed("GET", `datasets/${ID}/metrics`));
    assert.ok(allowed("POST", `datasets/${ID}/metrics`));
    assert.ok(allowed("POST", `datasets/${ID}/metrics/validate`));
    assert.ok(allowed("GET", `datasets/${ID}/metrics/total_revenue`));
    assert.ok(allowed("DELETE", `datasets/${ID}/metrics/total_revenue`));
    assert.ok(allowed("POST", `datasets/${ID}/metrics/total_revenue/versions`));
    assert.ok(allowed("POST", `datasets/${ID}/query`));
    assert.ok(allowed("POST", `datasets/${ID}/ask`));
    assert.ok(allowed("GET", `datasets/${ID}/pipeline`));
    assert.ok(allowed("get", `datasets/${ID}`)); // method case does not matter
});

test("wrong methods are refused", () => {
    assert.ok(!allowed("DELETE", `datasets/${ID}`));
    assert.ok(!allowed("POST", `datasets/${ID}`));
    assert.ok(!allowed("GET", `datasets/${ID}/ask`));
    assert.ok(!allowed("GET", `datasets/${ID}/query`));
    assert.ok(!allowed("POST", "health"));
    assert.ok(!allowed("PUT", "datasets"));
});

test("internal and unknown routes are never proxied", () => {
    assert.ok(!allowed("POST", "internal/maintenance/purge-guest-data"));
    assert.ok(!allowed("POST", "internal/maintenance/reprofile"));
    assert.ok(!allowed("GET", "docs"));
    assert.ok(!allowed("GET", "openapi.json"));
    assert.ok(!allowed("GET", "datasets/not-a-uuid"));
    assert.ok(!allowed("GET", `datasets/${ID}/unknown`));
    assert.ok(!allowed("GET", `datasets/${ID}/metrics/Bad-Name`));
    assert.ok(!allowed("GET", `datasets/${ID}/pipeline/extra`));
});

test("traversal and smuggling attempts are refused", () => {
    assert.ok(!isAllowedRequest("GET", []));
    assert.ok(!isAllowedRequest("GET", ["datasets", "..", "internal"]));
    assert.ok(!isAllowedRequest("GET", ["datasets", ".", ID]));
    assert.ok(!isAllowedRequest("GET", ["datasets", ""]));
    assert.ok(!isAllowedRequest("GET", ["datasets", `${ID}%2f..%2finternal`]));
    assert.ok(!isAllowedRequest("GET", ["datasets", `${ID}?x=1`]));
    assert.ok(!isAllowedRequest("GET", ["datasets", `${ID}#frag`]));
    assert.ok(!isAllowedRequest("GET", ["datasets\\x"]));
    assert.ok(!isAllowedRequest("GET", ["datasets", `${ID} `]));
    assert.ok(!isAllowedRequest("POST", ["internal", "maintenance", "purge-guest-data"]));
});

test("isUuid", () => {
    assert.ok(isUuid(ID));
    assert.ok(isUuid(ID.toUpperCase()));
    assert.ok(!isUuid("c56d392e"));
    assert.ok(!isUuid(`${ID}/x`));
    assert.ok(!isUuid(""));
});

test("upstreamUrl joins the base, path and a short query string", () => {
    assert.equal(upstreamUrl("http://api:8000/", ["datasets", ID], ""), `http://api:8000/datasets/${ID}`);
    assert.equal(upstreamUrl("http://api:8000", ["datasets"], "?limit=5"), "http://api:8000/datasets?limit=5");
    assert.equal(upstreamUrl("http://api:8000", ["datasets"], `?q=${"x".repeat(300)}`), "http://api:8000/datasets");
});

test("clientIpFrom takes the first forwarded address and rejects junk", () => {
    assert.equal(clientIpFrom(new Headers({ "x-forwarded-for": "203.0.113.9, 10.0.0.1" })), "203.0.113.9");
    assert.equal(clientIpFrom(new Headers({ "x-real-ip": "198.51.100.4" })), "198.51.100.4");
    assert.equal(clientIpFrom(new Headers({ "x-forwarded-for": "2001:db8::1" })), "2001:db8::1");
    assert.equal(clientIpFrom(new Headers({ "x-forwarded-for": "<script>" })), null);
    assert.equal(clientIpFrom(new Headers({ "x-forwarded-for": "1.2.3.4; DROP" })), null);
    assert.equal(clientIpFrom(new Headers()), null);
});

test("browser-supplied identity and cookies never reach the API", () => {
    const incoming = new Headers({
        "content-type": "multipart/form-data; boundary=abc",
        accept: "application/json",
        "x-user-id": "attacker",
        "x-internal-secret": "stolen",
        cookie: "session=1",
        authorization: "Bearer x",
        "x-forwarded-for": "6.6.6.6",
    });
    const guest = buildUpstreamHeaders(incoming, {}, "203.0.113.9");
    assert.equal(guest.get("content-type"), "multipart/form-data; boundary=abc");
    assert.equal(guest.get("accept"), "application/json");
    assert.equal(guest.get("x-user-id"), null);
    assert.equal(guest.get("x-internal-secret"), null);
    assert.equal(guest.get("cookie"), null);
    assert.equal(guest.get("authorization"), null);
    assert.equal(guest.get("x-forwarded-for"), "203.0.113.9");

    const signedIn = buildUpstreamHeaders(incoming, { "X-User-Id": "user-1", "X-Internal-Secret": "server-secret" }, null);
    assert.equal(signedIn.get("x-user-id"), "user-1");
    assert.equal(signedIn.get("x-internal-secret"), "server-secret");
    assert.equal(signedIn.get("x-forwarded-for"), null);
});

test("only safe response headers are passed back", () => {
    const upstream = new Headers({
        "content-type": "application/json",
        "retry-after": "20",
        "set-cookie": "a=b",
        server: "uvicorn",
        "x-internal-debug": "1",
    });
    const picked = pickResponseHeaders(upstream);
    assert.equal(picked.get("content-type"), "application/json");
    assert.equal(picked.get("retry-after"), "20");
    assert.equal(picked.get("set-cookie"), null);
    assert.equal(picked.get("server"), null);
    assert.equal(picked.get("x-internal-debug"), null);
});