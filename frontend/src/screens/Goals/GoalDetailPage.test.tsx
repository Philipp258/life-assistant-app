import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createTask, type Task } from "@/screens/Tasks/tasksApi";

import { GoalDetailPage } from "./GoalDetailPage";
import { deleteGoal, getGoal, updateGoal, type GoalDetail } from "./goalsApi";

vi.mock("@/shell/identity", () => ({
  useIdentity: () => ({
    assistantName: "Nix",
    isOnboarding: false,
    onboardingState: "done",
    refetch: vi.fn(),
  }),
}));

vi.mock("@/screens/Tasks/TaskRow", () => ({
  TaskRow: ({ task, onOpen }: { task: Task; onOpen: () => void }) => (
    <button type="button" data-testid="linked-task" onClick={onOpen}>
      {task.title}
    </button>
  ),
}));

vi.mock("@/screens/Tasks/tasksApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/screens/Tasks/tasksApi")>();
  return {
    ...actual,
    createTask: vi.fn(),
  };
});

vi.mock("./goalsApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./goalsApi")>();
  return {
    ...actual,
    deleteGoal: vi.fn(),
    getGoal: vi.fn(),
    updateGoal: vi.fn(),
  };
});

const deleteGoalMock = vi.mocked(deleteGoal);
const getGoalMock = vi.mocked(getGoal);
const updateGoalMock = vi.mocked(updateGoal);
const createTaskMock = vi.mocked(createTask);

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 9,
    title: "Write the UI",
    description: null,
    is_done: false,
    assignee: "assistant",
    chat_session_id: 19,
    goal_id: 3,
    goal_title: "Ship goals MVP",
    do_at: null,
    due_at: null,
    interval_unit: null,
    interval_count: null,
    created_at: "2026-05-01T10:00:00Z",
    updated_at: "2026-05-01T10:00:00Z",
    completed_at: null,
    state: "running",
    kind: "job",
    source_chat_session_id: null,
    source_chat_title: null,
    ...overrides,
  };
}

function makeGoal(overrides: Partial<GoalDetail> = {}): GoalDetail {
  return {
    id: 3,
    title: "Ship goals MVP",
    description: "Simple durable outcomes.",
    is_done: false,
    open_tasks_count: 1,
    done_tasks_count: 0,
    created_at: "2026-05-01T10:00:00Z",
    updated_at: "2026-05-02T10:00:00Z",
    completed_at: null,
    tasks: [makeTask()],
    events: [
      {
        id: 1,
        goal_id: 3,
        task_id: 9,
        task_title: "Write the UI",
        kind: "task_linked",
        body: "Task linked: Write the UI",
        created_at: "2026-05-02T10:00:00Z",
      },
    ],
    ...overrides,
  };
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderDetail() {
  render(
    <MemoryRouter initialEntries={["/goals/3"]}>
      <Routes>
        <Route
          path="/goals/:goalId"
          element={
            <>
              <GoalDetailPage />
              <LocationProbe />
            </>
          }
        />
        <Route path="/goals" element={<LocationProbe />} />
        <Route path="/tasks/:taskId" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  deleteGoalMock.mockReset();
  getGoalMock.mockReset();
  updateGoalMock.mockReset();
  createTaskMock.mockReset();
});

describe("GoalDetailPage", () => {
  it("renders details, linked tasks, and event log", async () => {
    getGoalMock.mockResolvedValue(makeGoal());
    renderDetail();

    expect(await screen.findByTestId("goal-title")).toHaveTextContent(
      "Ship goals MVP",
    );
    expect(screen.getByText("Simple durable outcomes.")).toBeInTheDocument();
    expect(screen.getByTestId("linked-task")).toHaveTextContent("Write the UI");
    expect(screen.getByText("Task linked: Write the UI")).toBeInTheDocument();

    await userEvent.click(screen.getByTestId("linked-task"));
    expect(screen.getByTestId("location")).toHaveTextContent("/tasks/9");
  });

  it("completes a goal through the API", async () => {
    const done = makeGoal({
      is_done: true,
      completed_at: "2026-05-03T10:00:00Z",
    });
    getGoalMock.mockResolvedValue(makeGoal());
    updateGoalMock.mockResolvedValue(done);
    renderDetail();

    await userEvent.click(await screen.findByTestId("goal-toggle-done"));
    expect(updateGoalMock).toHaveBeenCalledWith(3, { is_done: true });
    expect(await screen.findByText("Reopen")).toBeInTheDocument();
  });

  it("creates a linked task from the goal detail", async () => {
    getGoalMock
      .mockResolvedValueOnce(makeGoal({ tasks: [], open_tasks_count: 0 }))
      .mockResolvedValueOnce(
        makeGoal({
          tasks: [makeTask({ id: 12, title: "Call the printer" })],
          open_tasks_count: 1,
        }),
      );
    createTaskMock.mockResolvedValue(
      makeTask({ id: 12, title: "Call the printer" }),
    );
    renderDetail();

    await userEvent.type(
      await screen.findByLabelText("Task title"),
      "Call the printer",
    );
    await userEvent.click(screen.getByRole("button", { name: "Add task" }));

    expect(createTaskMock).toHaveBeenCalledWith({
      title: "Call the printer",
      assignee: "user",
      goal_id: 3,
    });
    expect(await screen.findByText("Call the printer")).toBeInTheDocument();
  });

  it("creates a linked task assigned to the assistant", async () => {
    getGoalMock
      .mockResolvedValueOnce(makeGoal({ tasks: [], open_tasks_count: 0 }))
      .mockResolvedValueOnce(
        makeGoal({
          tasks: [
            makeTask({
              id: 12,
              title: "Research treadmills",
              assignee: "assistant",
            }),
          ],
          open_tasks_count: 1,
        }),
      );
    createTaskMock.mockResolvedValue(
      makeTask({
        id: 12,
        title: "Research treadmills",
        assignee: "assistant",
      }),
    );
    renderDetail();

    await userEvent.type(
      await screen.findByLabelText("Task title"),
      "Research treadmills",
    );
    await userEvent.click(screen.getByLabelText("Assign new task to Nix"));
    await userEvent.click(screen.getByRole("button", { name: "Add task" }));

    expect(createTaskMock).toHaveBeenCalledWith({
      title: "Research treadmills",
      assignee: "assistant",
      goal_id: 3,
    });
  });

  it("deletes a goal after confirmation and returns to goals", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    getGoalMock.mockResolvedValue(makeGoal());
    deleteGoalMock.mockResolvedValue(undefined);
    renderDetail();

    await userEvent.click(await screen.findByTestId("goal-delete"));

    expect(confirmSpy).toHaveBeenCalledWith(
      'Delete "Ship goals MVP"? Linked tasks will stay, but their goal link and goal log will be removed. This cannot be undone.',
    );
    expect(deleteGoalMock).toHaveBeenCalledWith(3);
    expect(await screen.findByTestId("location")).toHaveTextContent("/goals");
    confirmSpy.mockRestore();
  });

  it("keeps a goal when delete confirmation is cancelled", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    getGoalMock.mockResolvedValue(makeGoal());
    renderDetail();

    await userEvent.click(await screen.findByTestId("goal-delete"));

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(deleteGoalMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("location")).toHaveTextContent("/goals/3");
    confirmSpy.mockRestore();
  });
});
