import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TasksScreen } from "./TasksScreen";
import type { Task } from "./tasksApi";
import type { SavedTaskView } from "./savedTaskViewsApi";

vi.mock("./tasksApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./tasksApi")>();
  return {
    ...actual,
    listTasks: vi.fn(),
    listDoneTasks: vi.fn().mockResolvedValue({ tasks: [], nextCursor: null }),
    fetchTaskActivity: vi.fn().mockResolvedValue({
      active_session_ids: [],
      stalled_session_ids: [],
      errored_session_ids: [],
    }),
    updateTask: vi.fn().mockResolvedValue({}),
    createTask: vi.fn(),
  };
});

vi.mock("./savedTaskViewsApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./savedTaskViewsApi")>();
  return {
    ...actual,
    listViews: vi.fn(),
    createView: vi.fn(),
    updateView: vi.fn(),
    deleteView: vi.fn(),
  };
});

import { createView, listViews, updateView } from "./savedTaskViewsApi";
import { fetchTaskActivity, listDoneTasks, listTasks } from "./tasksApi";

const listTasksMock = vi.mocked(listTasks);
const listDoneTasksMock = vi.mocked(listDoneTasks);
const fetchTaskActivityMock = vi.mocked(fetchTaskActivity);
const listViewsMock = vi.mocked(listViews);
const createViewMock = vi.mocked(createView);
const updateViewMock = vi.mocked(updateView);

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 1,
    title: "T",
    description: null,
    is_done: false,
    assignee: "user",
    chat_session_id: 1,
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

function makeView(overrides: Partial<SavedTaskView> = {}): SavedTaskView {
  return {
    id: 1,
    name: "Inbox",
    icon: "📥",
    filters: {},
    group_by: "none",
    sort_index: 0,
    is_default: true,
    ...overrides,
  };
}

beforeEach(() => {
  listTasksMock.mockReset();
  listDoneTasksMock.mockReset();
  listDoneTasksMock.mockResolvedValue({ tasks: [], nextCursor: null });
  fetchTaskActivityMock.mockReset();
  fetchTaskActivityMock.mockResolvedValue({
    active_session_ids: [],
    stalled_session_ids: [],
    errored_session_ids: [],
  });
  listViewsMock.mockReset();
  listViewsMock.mockResolvedValue([makeView()]);
  createViewMock.mockReset();
  updateViewMock.mockReset();
});

function renderScreen() {
  return render(
    <MemoryRouter>
      <TasksScreen />
    </MemoryRouter>,
  );
}

function LocationProbe() {
  const location = useLocation();
  return (
    <div data-testid="probe-search">{location.search}</div>
  );
}

describe("TasksScreen", () => {
  it("renders the active saved task view tab", async () => {
    listTasksMock.mockResolvedValue([]);
    renderScreen();
    expect(await screen.findByText("Inbox")).toBeInTheDocument();
  });

  it("calls listTasks with the active view's filters on mount", async () => {
    listViewsMock.mockResolvedValue([
      makeView({ filters: { statuses: ["open"] } }),
    ]);
    listTasksMock.mockResolvedValue([]);
    renderScreen();

    await waitFor(() => {
      expect(listTasksMock).toHaveBeenCalledWith({
        statuses: ["open"],
        done: false,
      });
    });
  });

  it("switching tabs triggers listTasks with the new view's filter blob", async () => {
    listViewsMock.mockResolvedValue([
      makeView({ id: 1, name: "Inbox", filters: {}, is_default: true }),
      makeView({
        id: 2,
        name: "Mine",
        filters: { assignee: "user" },
        is_default: false,
      }),
    ]);
    listTasksMock.mockResolvedValue([]);
    renderScreen();

    // Initial load with default view's empty filters
    await waitFor(() => expect(listTasksMock).toHaveBeenCalledWith({ done: false }));

    await userEvent.click(await screen.findByText("Mine"));

    await waitFor(() => {
      expect(listTasksMock).toHaveBeenCalledWith({ assignee: "user", done: false });
    });
  });

  it("does not issue an initial unfiltered main-list fetch before saved views hydrate", async () => {
    listViewsMock.mockResolvedValue([
      makeView({ filters: { statuses: ["open"] } }),
    ]);
    listTasksMock.mockImplementation(async (params = {}) =>
      params.statuses?.includes("open")
        ? [makeTask({ id: 1, title: "Open task" })]
        : [
            makeTask({
              id: 2,
              title: "Done task",
              is_done: true,
              state: "done",
              completed_at: "2026-05-01T11:00:00Z",
            }),
          ],
    );

    renderScreen();

    expect((await screen.findAllByText("Open task")).length).toBeGreaterThan(0);
    expect(screen.queryByText("Done task")).not.toBeInTheDocument();
    expect(listTasksMock).toHaveBeenCalledWith({ statuses: ["open"], done: false });
    expect(listTasksMock).not.toHaveBeenCalledWith({});
  });

  it("ignores legacy saved-view grouping and renders one flat list", async () => {
    listViewsMock.mockResolvedValue([
      makeView({ group_by: "status" as never }),
    ]);
    listTasksMock.mockResolvedValue([
      makeTask({ id: 1, title: "Active todo" }),
      makeTask({
        id: 2,
        title: "Future deadline",
        due_at: "2099-04-15T00:00:00Z",
      }),
    ]);
    renderScreen();

    expect((await screen.findAllByText("Active todo")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("Future deadline")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("region", { name: "Working now" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Scheduled" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /group/i })).not.toBeInTheDocument();
  });

  it("new task composer is openable from the header", async () => {
    listTasksMock.mockResolvedValue([]);
    renderScreen();
    await userEvent.click(
      await screen.findByRole("button", { name: /^new/i }),
    );
    expect(await screen.findByLabelText("Title")).toBeInTheDocument();
  });

  it("opens the filter sheet from the toolbar", async () => {
    listTasksMock.mockResolvedValue([]);
    renderScreen();
    await userEvent.click(
      await screen.findByRole("button", { name: /^filters/i }),
    );
    expect(await screen.findByText("Filters")).toBeInTheDocument();
  });

  it("syncs the active view + filter overrides to the URL", async () => {
    listViewsMock.mockResolvedValue([
      makeView({ id: 1, name: "Inbox", filters: {}, is_default: true }),
      makeView({
        id: 2,
        name: "Mine",
        filters: { assignee: "user" },
        is_default: false,
      }),
    ]);
    listTasksMock.mockResolvedValue([]);

    render(
      <MemoryRouter initialEntries={["/tasks"]}>
        <Routes>
          <Route
            path="/tasks"
            element={
              <>
                <LocationProbe />
                <TasksScreen />
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    await screen.findByText("Inbox");
    // Default view (id=1, is_default) gets reflected in the URL.
    await waitFor(() =>
      expect(screen.getByTestId("probe-search").textContent).toContain(
        "view=1",
      ),
    );

    await userEvent.click(screen.getByText("Mine"));
    await waitFor(() => {
      const search = screen.getByTestId("probe-search").textContent ?? "";
      expect(search).toContain("view=2");
      expect(search).toContain("assignee=user");
      expect(search).not.toContain("labels=");
      expect(search).not.toContain("group=");
    });
  });

  it("restores filters from the URL on mount (back-navigation round-trip)", async () => {
    listViewsMock.mockResolvedValue([
      makeView({ id: 1, name: "Inbox", filters: {}, is_default: true }),
      makeView({
        id: 2,
        name: "Mine",
        filters: { assignee: "user" },
        is_default: false,
      }),
    ]);
    listTasksMock.mockResolvedValue([]);

    // Simulate the URL the user would land on after navigating back from a
    // task detail: view=2 with explicit overrides preserved in the query
    // string.
    render(
      <MemoryRouter
        initialEntries={[
          "/tasks?view=2&statuses=open&labels=home&assignee=user",
        ]}
      >
        <TasksScreen />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(listTasksMock).toHaveBeenCalledWith({
        statuses: ["open"],
        assignee: "user",
        done: false,
      });
    });
    expect(await screen.findByText("Mine")).toBeInTheDocument();
  });

  it("filters the visible tasks by the below-title search input", async () => {
    listTasksMock.mockResolvedValue([
      makeTask({ id: 1, title: "Reply to Anna" }),
      makeTask({ id: 2, title: "Pick groceries" }),
      makeTask({ id: 3, title: "File quarterly taxes" }),
    ]);
    renderScreen();

    expect((await screen.findAllByText("Reply to Anna")).length).toBeGreaterThan(0);

    await userEvent.type(
      screen.getByRole("searchbox", { name: /search tasks/i }),
      "groceries",
    );

    await waitFor(() =>
      expect(screen.queryByText("Reply to Anna")).not.toBeInTheDocument(),
    );
    expect(screen.getAllByText("Pick groceries").length).toBeGreaterThan(0);
    expect(screen.queryByText("File quarterly taxes")).not.toBeInTheDocument();
  });

  it("keeps search out of saved-view dirty state and created view payloads", async () => {
    listTasksMock.mockResolvedValue([
      makeTask({ id: 1, title: "Reply to Anna" }),
      makeTask({ id: 2, title: "Pick groceries" }),
    ]);
    createViewMock.mockResolvedValue(makeView({ id: 3, name: "Groceries" }));
    renderScreen();

    expect((await screen.findAllByText("Reply to Anna")).length).toBeGreaterThan(0);

    await userEvent.type(
      screen.getByRole("searchbox", { name: /search tasks/i }),
      "groceries",
    );

    expect(screen.getByRole("button", { name: /save view/i })).toBeDisabled();
    expect(screen.queryByLabelText("unsaved")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /new view/i }));
    await userEvent.type(screen.getByLabelText("View name"), "Groceries");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(createViewMock).toHaveBeenCalledWith({
        name: "Groceries",
        icon: null,
        filters: {},
        group_by: "none",
      }),
    );
    expect(createViewMock.mock.calls[0][0]).not.toHaveProperty("search");
    expect(updateViewMock).not.toHaveBeenCalled();
  });

  it("shows a search-specific empty state when no task matches the query", async () => {
    listTasksMock.mockResolvedValue([makeTask({ id: 1, title: "Reply to Anna" })]);
    renderScreen();

    await screen.findAllByText("Reply to Anna");

    await userEvent.type(
      screen.getByRole("searchbox", { name: /search tasks/i }),
      "zzz-no-match",
    );

    expect(
      await screen.findByText(/No tasks match "zzz-no-match"/),
    ).toBeInTheDocument();
  });

  it("keeps the done archive lazy until opened", async () => {
    listTasksMock.mockResolvedValue([]);
    renderScreen();

    await screen.findByRole("button", { name: /done archive/i });
    expect(listDoneTasksMock).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: /done archive/i }));

    await waitFor(() =>
      expect(listDoneTasksMock).toHaveBeenCalledWith(
        expect.objectContaining({}),
        null,
      ),
    );
  });

  it("scopes the done archive to the active view filters", async () => {
    listViewsMock.mockResolvedValue([
      makeView({
        filters: { assignee: "user", statuses: ["open"] },
      }),
    ]);
    listTasksMock.mockResolvedValue([]);
    renderScreen();

    await userEvent.click(await screen.findByRole("button", { name: /done archive/i }));

    await waitFor(() =>
      expect(listDoneTasksMock).toHaveBeenCalledWith(
        expect.objectContaining({
          assignee: "user",
        }),
        null,
      ),
    );
    expect(listDoneTasksMock.mock.calls[0][0]).not.toHaveProperty("statuses");
    expect(listDoneTasksMock.mock.calls[0][0]).not.toHaveProperty("labels");
  });

  it("shows an undo toast after a row check-off and reverts on Undo", async () => {
    const updateTaskMock = vi.mocked(
      (await import("./tasksApi")).updateTask,
    );
    updateTaskMock.mockResolvedValue(
      makeTask({ id: 7, title: "Mark me", is_done: true }),
    );
    listTasksMock.mockResolvedValue([
      makeTask({ id: 7, title: "Mark me", assignee: "user" }),
    ]);

    renderScreen();
    await screen.findAllByText("Mark me");

    await userEvent.click(
      screen.getByRole("button", { name: /mark as done/i }),
    );

    // Banner appears.
    const toast = await screen.findByTestId("task-undo-toast");
    expect(toast).toHaveTextContent(/Mark me/);

    await userEvent.click(screen.getByTestId("task-undo-button"));
    // Reverse patch fires.
    expect(updateTaskMock).toHaveBeenLastCalledWith(7, { is_done: false });
  });

  it("disables Create and shows 'Picking emoji…' while createView is in flight", async () => {
    listTasksMock.mockResolvedValue([]);
    let resolveCreate: (value: SavedTaskView) => void = () => {};
    createViewMock.mockImplementation(
      () =>
        new Promise<SavedTaskView>((resolve) => {
          resolveCreate = resolve;
        }),
    );

    renderScreen();

    // Wait for the views to load and the tabs to render.
    await screen.findByText("Inbox");

    // Open the new-view prompt.
    await userEvent.click(screen.getByRole("button", { name: "New view" }));

    // Type a name and click Create.
    const input = await screen.findByLabelText("View name");
    await userEvent.type(input, "Daily");
    await userEvent.click(screen.getByRole("button", { name: /^create$/i }));

    // Synchronous assertions: the POST is in flight and never resolves.
    expect(screen.getByRole("button", { name: /^create$/i })).toBeDisabled();
    expect(screen.getByText(/Picking emoji…/)).toBeInTheDocument();

    // Resolve the promise so React's act() bookkeeping winds down cleanly.
    resolveCreate(
      makeView({ id: 99, name: "Daily", icon: "✨", is_default: false }),
    );
    await waitFor(() =>
      expect(screen.queryByText(/Picking emoji…/)).not.toBeInTheDocument(),
    );
  });
});
