import { describe, expect, it, vi } from "vitest";
import {
  createView,
  listViews,
  reorderViews,
  updateView,
} from "./savedTaskViewsApi";

describe("savedTaskViewsApi", () => {
  it("listViews returns array", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ views: [] }), { status: 200 }),
    );
    expect(await listViews()).toEqual([]);
  });

  it("createView posts filters and group_by", async () => {
    const mock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ id: 5, name: "x" }), { status: 201 }),
    );
    await createView({ name: "x", filters: { assignee: "user" }, group_by: "none" });
    const call = mock.mock.calls[0]!;
    expect(JSON.parse((call[1] as RequestInit).body as string).filters.assignee).toBe("user");
  });

  it("updateView patches", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ id: 5 }), { status: 200 }),
    );
    await updateView(5, { name: "y" });
  });

  it("reorderViews sends a sort_index PATCH for every id, in order", async () => {
    const calls: Array<{ url: string; body: unknown }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((async (
      url: RequestInfo,
      init?: RequestInit,
    ) => {
      calls.push({
        url: String(url),
        body: init?.body ? JSON.parse(init.body as string) : null,
      });
      const id = Number(String(url).match(/\d+/)?.[0] ?? 0);
      return new Response(JSON.stringify({ id }), { status: 200 });
    }) as typeof globalThis.fetch);

    await reorderViews([7, 3, 11]);

    expect(calls).toHaveLength(3);
    expect(calls.map((c) => c.body)).toEqual([
      { sort_index: 0 },
      { sort_index: 1 },
      { sort_index: 2 },
    ]);
    expect(calls.map((c) => c.url)).toEqual([
      "/api/saved-task-views/7",
      "/api/saved-task-views/3",
      "/api/saved-task-views/11",
    ]);
  });
});
