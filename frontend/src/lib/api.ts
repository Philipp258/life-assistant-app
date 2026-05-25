// Centralised fetch wrapper. Adds cookie credentials and redirects to
// /login on 401 so individual API modules don't have to care about auth.

const AUTH_PREFIX = "/api/auth/";

export async function apiFetch(
  input: string,
  init?: RequestInit,
): Promise<Response> {
  const r = await fetch(input, { credentials: "same-origin", ...init });
  if (r.status === 401 && !input.startsWith(AUTH_PREFIX)) {
    if (
      typeof window !== "undefined" &&
      window.location.pathname !== "/login"
    ) {
      window.location.href = "/login";
    }
    throw new Error("Unauthenticated");
  }
  return r;
}

export async function jsonOrThrow<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const body = await r.text().catch(() => "");
    throw new Error(`${r.status} ${r.statusText}: ${body}`);
  }
  // If the server returned the SPA document (e.g. a stale client hitting
  // an unknown API path), surface a useful error instead of the opaque
  // "Unexpected token '<'" from blindly calling r.json().
  const contentType = r.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().includes("json")) {
    throw new Error(
      `Expected JSON from ${r.url}, got ${contentType || "no content-type"}`,
    );
  }
  return (await r.json()) as T;
}
