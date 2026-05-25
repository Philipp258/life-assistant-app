import { describe, expect, it, vi } from "vitest";

import { createLabel, listLabels } from "./labelsApi";

describe("labelsApi", () => {
  it("listLabels hits /api/labels and returns the array", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ labels: [{ id: 1, slug: "a", name: "A" }] }), { status: 200 }),
    );
    const out = await listLabels();
    expect(fetchMock).toHaveBeenCalledWith("/api/labels", expect.anything());
    expect(out).toEqual([{ id: 1, slug: "a", name: "A" }]);
  });

  it("createLabel posts the body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ id: 9, slug: "x", name: "X" }), { status: 201 }),
    );
    const out = await createLabel({ slug: "x", name: "X" });
    expect(out.id).toBe(9);
  });
});
