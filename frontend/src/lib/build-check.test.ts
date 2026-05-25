import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { installBuildCheck } from "./build-check";

// `__LIFE_ASSISTANT_BUILD_ID__` is injected by vitest.config.ts as "test-build".

function fireVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

function indexHtmlWithBuild(id: string): string {
  return `<!doctype html><html><head><meta name="life-assistant-build-id" content="${id}" />` +
    `<title>Life Assistant</title></head><body><div id="root"></div></body></html>`;
}

describe("installBuildCheck", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let reloadMock: ReturnType<typeof vi.fn>;
  let teardown: (() => void) | null = null;
  let nowMs = 0;

  beforeEach(() => {
    nowMs = 1_000_000;
    fetchMock = vi.fn();
    reloadMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    fireVisibility("visible");
  });

  afterEach(() => {
    teardown?.();
    teardown = null;
    vi.unstubAllGlobals();
  });

  it("does nothing when the served build id matches", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(indexHtmlWithBuild("test-build"), { status: 200 }),
    );

    teardown = installBuildCheck({
      now: () => nowMs,
      reload: reloadMock,
    });

    // Hide for long enough to clear the 60s threshold, then show.
    fireVisibility("hidden");
    nowMs += 120_000;
    fireVisibility("visible");

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(reloadMock).not.toHaveBeenCalled();
  });

  it("reloads when the served build differs and the document was hidden long enough", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(indexHtmlWithBuild("new-build"), { status: 200 }),
    );

    teardown = installBuildCheck({
      now: () => nowMs,
      reload: reloadMock,
    });

    fireVisibility("hidden");
    nowMs += 120_000;
    fireVisibility("visible");

    await vi.waitFor(() => expect(reloadMock).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith(
      "/index.html",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("defers the reload when the user only briefly switched away", async () => {
    fetchMock.mockResolvedValue(
      new Response(indexHtmlWithBuild("new-build"), { status: 200 }),
    );

    teardown = installBuildCheck({
      now: () => nowMs,
      reload: reloadMock,
    });

    // First foreground after a 5s hide → detect mismatch but defer.
    fireVisibility("hidden");
    nowMs += 5_000;
    fireVisibility("visible");

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(reloadMock).not.toHaveBeenCalled();

    // Now the user backgrounds for >60s and returns → reload.
    fireVisibility("hidden");
    nowMs += 120_000;
    fireVisibility("visible");

    await vi.waitFor(() => expect(reloadMock).toHaveBeenCalledTimes(1));
  });
});
