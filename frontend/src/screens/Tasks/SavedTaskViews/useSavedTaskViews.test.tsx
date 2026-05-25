import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { useSavedTaskViews } from "./useSavedTaskViews";

vi.mock("../savedTaskViewsApi", () => ({
  listViews: vi.fn().mockResolvedValue([
    {
      id: 1,
      name: "Inbox",
      icon: "📥",
      filters: {},
      group_by: "none",
      sort_index: 0,
      is_default: true,
    },
    {
      id: 2,
      name: "Home",
      icon: "🏠",
      filters: { labels: ["home"] },
      group_by: "none",
      sort_index: 1,
      is_default: false,
    },
  ]),
  createView: vi.fn().mockResolvedValue({
    id: 2,
    name: "Home",
    icon: "🏠",
    filters: { labels: ["home"] },
    group_by: "none",
    sort_index: 1,
    is_default: false,
  }),
  updateView: vi.fn(),
  deleteView: vi.fn(),
  reorderViews: vi.fn().mockImplementation(async (orderedIds: number[]) =>
    orderedIds.map((id, idx) => ({
      id,
      name: `View ${id}`,
      icon: null,
      filters: {},
      group_by: "none" as const,
      sort_index: idx,
      is_default: false,
    })),
  ),
}));

function wrapperFor(initialEntry = "/tasks") {
  return ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={[initialEntry]}>{children}</MemoryRouter>
  );
}

function UrlProbeHarness() {
  const state = useSavedTaskViews();
  const location = useLocation();
  return (
    <>
      <div data-testid="search">{location.search}</div>
      <div data-testid="filters">{JSON.stringify(state.workingFilters)}</div>
      <div data-testid="dirty">{String(state.dirty)}</div>
      <button type="button" onClick={() => state.editFilters({ labels: [] })}>
        Clear labels
      </button>
    </>
  );
}

describe("useSavedTaskViews", () => {
  it("loads views and picks the default as active", async () => {
    const { result } = renderHook(() => useSavedTaskViews(), {
      wrapper: wrapperFor(),
    });
    await waitFor(() => expect(result.current.views.length).toBe(2));
    expect(result.current.activeView.name).toBe("Inbox");
  });

  it("dirty flips true after editFilters", async () => {
    const { result } = renderHook(() => useSavedTaskViews(), {
      wrapper: wrapperFor(),
    });
    await waitFor(() => expect(result.current.views.length).toBe(2));
    act(() => result.current.editFilters({ labels: ["x"] }));
    expect(result.current.dirty).toBe(true);
  });

  it("hydrates filters from URL search params", async () => {
    const { result } = renderHook(() => useSavedTaskViews(), {
      wrapper: wrapperFor(
        "/tasks?view=1&statuses=open,scheduled&labels=home&assignee=user&due=today&group=status",
      ),
    });
    await waitFor(() => expect(result.current.views.length).toBe(2));
    expect(result.current.activeView.id).toBe(1);
    expect(result.current.workingFilters).toEqual({
      statuses: ["open", "scheduled"],
      labels: ["home"],
      assignee: "user",
      due: "today",
    });
    // URL had explicit overrides — working state is dirty vs. the saved view.
    expect(result.current.dirty).toBe(true);
  });

  it("falls back to view defaults when URL only specifies view id", async () => {
    const { result } = renderHook(() => useSavedTaskViews(), {
      wrapper: wrapperFor("/tasks?view=2"),
    });
    await waitFor(() => expect(result.current.views.length).toBe(2));
    expect(result.current.activeView.id).toBe(2);
    expect(result.current.workingFilters).toEqual({ labels: ["home"] });
    expect(result.current.dirty).toBe(false);
  });

  it("round-trips explicitly cleared saved-view filters through the URL", async () => {
    render(
      <MemoryRouter initialEntries={["/tasks?view=2"]}>
        <UrlProbeHarness />
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("filters").textContent).toBe(
        JSON.stringify({ labels: ["home"] }),
      ),
    );

    act(() => screen.getByRole("button", { name: "Clear labels" }).click());

    await waitFor(() => {
      expect(screen.getByTestId("filters").textContent).toBe(
        JSON.stringify({ labels: [] }),
      );
      const search = screen.getByTestId("search").textContent ?? "";
      expect(search).toContain("view=2");
      expect(search).toContain("labels=");
      expect(screen.getByTestId("dirty").textContent).toBe("true");
    });
  });

  it("reorderViews reflows tabs optimistically and persists the new order", async () => {
    const { result } = renderHook(() => useSavedTaskViews(), {
      wrapper: wrapperFor(),
    });
    await waitFor(() => expect(result.current.views.length).toBe(2));
    expect(result.current.views.map((v) => v.id)).toEqual([1, 2]);

    await act(async () => {
      await result.current.reorderViews([2, 1]);
    });

    expect(result.current.views.map((v) => v.id)).toEqual([2, 1]);
    expect(result.current.views[0].sort_index).toBe(0);
    expect(result.current.views[1].sort_index).toBe(1);
  });

  it("hydrates explicitly cleared saved-view filters from the URL", async () => {
    const { result } = renderHook(() => useSavedTaskViews(), {
      wrapper: wrapperFor("/tasks?view=2&labels=&group=none"),
    });
    await waitFor(() => expect(result.current.views.length).toBe(2));
    expect(result.current.activeView.id).toBe(2);
    expect(result.current.workingFilters).toEqual({ labels: [] });
    expect(result.current.dirty).toBe(true);
  });
});
