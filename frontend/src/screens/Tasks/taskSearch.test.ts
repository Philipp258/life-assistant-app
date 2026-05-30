import { describe, expect, it } from "vitest";

import { filterTasksBySearch, matchesTaskSearch, tokenize } from "./taskSearch";
import type { Task } from "./tasksApi";

function t(overrides: Partial<Task>): Task {
  return {
    id: 1,
    title: "Untitled",
    description: null,
    is_done: false,
    assignee: "user",
    chat_session_id: 0,
    goal_id: null,
    goal_title: null,
    do_at: null,
    due_at: null,
    interval_unit: null,
    interval_count: null,
    created_at: "2026-05-01T10:00:00Z",
    updated_at: "2026-05-01T10:00:00Z",
    completed_at: null,
    state: "yours",
    kind: "todo",
    source_chat_session_id: null,
    source_chat_title: null,
    ...overrides,
  };
}

describe("tokenize", () => {
  it("splits on whitespace, lowercases, drops empties", () => {
    expect(tokenize("  Reply  to  Anna  ")).toEqual(["reply", "to", "anna"]);
  });

  it("returns empty array for whitespace-only query", () => {
    expect(tokenize("   ")).toEqual([]);
  });
});

describe("matchesTaskSearch", () => {
  it("matches any task when query is empty", () => {
    expect(matchesTaskSearch(t({ title: "Reply to Anna" }), "")).toBe(true);
  });

  it("matches case-insensitively on title", () => {
    expect(matchesTaskSearch(t({ title: "Reply to Anna" }), "anna")).toBe(true);
    expect(matchesTaskSearch(t({ title: "Reply to Anna" }), "BOB")).toBe(false);
  });

  it("matches on description", () => {
    const task = t({ title: "Errand", description: "Buy groceries at the corner" });
    expect(matchesTaskSearch(task, "groceries")).toBe(true);
  });

  it("requires all tokens to be present (AND semantics)", () => {
    const task = t({ title: "File quarterly taxes", description: "April deadline" });
    expect(matchesTaskSearch(task, "tax april")).toBe(true);
    expect(matchesTaskSearch(task, "tax november")).toBe(false);
  });
});

describe("filterTasksBySearch", () => {
  const rows = [
    t({ id: 1, title: "Reply to Anna" }),
    t({ id: 2, title: "Pick groceries on the way home" }),
    t({ id: 3, title: "File quarterly taxes" }),
  ];

  it("returns all when query is empty", () => {
    expect(filterTasksBySearch(rows, "  ")).toHaveLength(3);
  });

  it("filters by query", () => {
    const out = filterTasksBySearch(rows, "groceries");
    expect(out.map((r) => r.id)).toEqual([2]);
  });
});
