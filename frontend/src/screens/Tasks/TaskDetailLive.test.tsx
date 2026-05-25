import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatWireEvent } from "../Chat/chatChannel";
import type { Task } from "./tasksApi";

const mocks = vi.hoisted(() => {
  let listener: ((event: any) => void) | null = null;
  const remove = vi.fn();
  return {
    getListener: () => listener,
    clearListener: () => {
      listener = null;
    },
    addListener: vi.fn((fn: (event: any) => void) => {
      listener = fn;
      return remove;
    }),
    remove,
    getTask: vi.fn(),
    getChatMessages: vi.fn(),
    fetchTaskActivity: vi.fn(),
    updateTask: vi.fn(),
    deleteTask: vi.fn(),
    runTaskNow: vi.fn(),
  };
});

vi.mock("@/shell/identity", () => ({
  useIdentity: () => ({
    assistantName: "Nix",
    isOnboarding: false,
    onboardingState: "done",
    refetch: vi.fn(),
  }),
}));

vi.mock("../Chat/chatChannel", () => ({
  getChatChannel: () => ({ addListener: mocks.addListener }),
}));

vi.mock("../Chat/chatApi", () => ({
  getChatMessages: mocks.getChatMessages,
}));

vi.mock("./TaskActivityThread", () => ({
  TaskActivityThread: ({ task }: { task: Task }) => (
    <div data-testid="task-thread">Thread: {task.title}</div>
  ),
}));

vi.mock("./tasksApi", () => ({
  getTask: mocks.getTask,
  updateTask: mocks.updateTask,
  deleteTask: mocks.deleteTask,
  runTaskNow: mocks.runTaskNow,
  fetchTaskActivity: mocks.fetchTaskActivity,
}));

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 1,
    title: "Initial task",
    description: "Initial description",
    is_done: false,
    assignee: "user",
    labels: [],
    chat_session_id: 10,
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

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

async function renderTaskDetail(task = makeTask()) {
  mocks.getTask.mockResolvedValue(task);
  mocks.getChatMessages.mockResolvedValue([]);
  mocks.fetchTaskActivity.mockResolvedValue({
    active_session_ids: [],
    stalled_session_ids: [],
    errored_session_ids: [],
  });

  const { TaskDetailPage } = await import("./TaskDetailPage");
  render(
    <MemoryRouter initialEntries={["/tasks/1"]}>
      <Routes>
        <Route path="/tasks/:taskId" element={<TaskDetailPage />} />
        <Route path="/tasks" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );

  await screen.findByTestId("task-title-static");
  await waitFor(() => expect(mocks.addListener).toHaveBeenCalled());
}

describe("TaskDetailPage live task events", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.clearListener();
  });

  it("applies task_upsert without remounting the activity thread", async () => {
    await renderTaskDetail();
    expect(screen.getByTestId("task-title-static")).toHaveTextContent(
      "Initial task",
    );

    const listener = mocks.getListener();
    expect(listener).toBeTypeOf("function");
    act(() => {
      listener?.({
        type: "task_upsert",
        session_id: 10,
        task_id: 1,
        task: makeTask({ title: "Renamed task" }),
      } satisfies ChatWireEvent);
    });

    expect(screen.getByTestId("task-title-static")).toHaveTextContent(
      "Renamed task",
    );
    expect(screen.getByTestId("task-thread")).toHaveTextContent(
      "Renamed task",
    );
  });

  it("ignores snapshots as task-row invalidation", async () => {
    await renderTaskDetail();
    expect(mocks.getTask).toHaveBeenCalledTimes(1);

    act(() => {
      mocks.getListener()?.({
        type: "snapshot",
        session_id: 10,
        messages: [],
      } satisfies ChatWireEvent);
    });

    expect(mocks.getTask).toHaveBeenCalledTimes(1);
  });

  it("navigates away when the open task is deleted elsewhere", async () => {
    await renderTaskDetail();

    act(() => {
      mocks.getListener()?.({
        type: "task_delete",
        session_id: 10,
        task_id: 1,
      } satisfies ChatWireEvent);
    });

    expect(await screen.findByTestId("location")).toHaveTextContent("/tasks");
  });
});
