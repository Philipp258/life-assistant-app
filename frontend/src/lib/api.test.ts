import { describe, expect, it } from "vitest";

import { jsonOrThrow } from "./api";

function htmlResponse(): Response {
  return new Response("<!doctype html><html></html>", {
    status: 200,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("jsonOrThrow", () => {
  it("parses JSON on a 2xx JSON response", async () => {
    const r = jsonResponse({ ok: true });
    await expect(jsonOrThrow<{ ok: boolean }>(r)).resolves.toEqual({ ok: true });
  });

  it("throws a useful error when the server returns HTML with a 200 (stale SPA fallthrough)", async () => {
    // Without this guard, callers would get the opaque
    // "Unexpected token '<', \"<!doctype \"..." JSON parse error.
    await expect(jsonOrThrow(htmlResponse())).rejects.toThrow(/Expected JSON/);
  });

  it("includes status + body when the response is not ok", async () => {
    const r = new Response("nope", { status: 500, statusText: "Boom" });
    await expect(jsonOrThrow(r)).rejects.toThrow(/500 .*nope/);
  });
});
