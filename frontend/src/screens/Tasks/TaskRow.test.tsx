import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TaskRow } from "./TaskRow";
import type { Task } from "./tasksApi";

vi.mock("./tasksApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./tasksApi")>();
  return {
    ...actual,
    updateTask: vi.fn().mockResolvedValue({}),
    runTaskNow: vi.fn().mockResolvedValue({}),
  };
});

import { runTaskNow, updateTask } from "./tasksApi";

const updateTaskMock = vi.mocked(updateTask);
const runTaskNowMock = vi.mocked(runTaskNow);

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 7,
    title: "Row task",
    description: null,
    is_done: false,
    assignee: "user",
    chat_session_id: 11,
    goal_id: null,
    goal_title: null,
    do_at: null,
    due_at: null,
    interval_unit: null,
    interval_count: null,
    created_at: "2026-04-30T10:00:00Z",
    updated_at: "2026-04-30T10:00:00Z",
    completed_at: null,
    state: "yours",
    kind: "todo",
    source_chat_session_id: null,
    source_chat_title: null,
    ...overrides,
  };
}

beforeEach(() => {
  updateTaskMock.mockClear();
  runTaskNowMock.mockClear();
});

describe("TaskRow", () => {
  it("shows the Done checkbox on agent tasks (enabled when not live)", () => {
    render(
      <TaskRow
        task={makeTask({ assignee: "assistant", is_done: false })}
        onOpen={vi.fn()}
        assistantName="Nix"
      />,
    );

    const cb = screen.getByRole("button", { name: /mark as done/i });
    expect(cb).toBeInTheDocument();
    expect(cb).toBeEnabled();
  });

  it("greys/disables the Done checkbox while the agent is live", () => {
    render(
      <TaskRow
        task={makeTask({ assignee: "assistant", is_done: false })}
        onOpen={vi.fn()}
        isLive
        assistantName="Nix"
      />,
    );

    expect(
      screen.getByRole("button", { name: /mark as done/i }),
    ).toBeDisabled();
  });

  it("shows the Done checkbox on an idle user-assigned task", () => {
    render(
      <TaskRow
        task={makeTask({ assignee: "user", is_done: false })}
        onOpen={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: /mark as done/i }),
    ).toBeInTheDocument();
  });

  it("clicking the Done checkbox calls updateTask with is_done=true", async () => {
    const task = makeTask({ assignee: "user", is_done: false });
    const onOpen = vi.fn();
    render(<TaskRow task={task} onOpen={onOpen} />);

    await userEvent.click(
      screen.getByRole("button", { name: /mark as done/i }),
    );

    expect(updateTaskMock).toHaveBeenCalledTimes(1);
    expect(updateTaskMock).toHaveBeenCalledWith(task.id, { is_done: true });
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("clicking the row body opens the task", async () => {
    const onOpen = vi.fn();
    render(
      <TaskRow
        task={makeTask({ assignee: "user", is_done: false })}
        onOpen={onOpen}
      />,
    );

    await userEvent.click(screen.getByText("Row task"));

    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("does not open the task if a text selection is active", async () => {
    const onOpen = vi.fn();
    render(
      <TaskRow
        task={makeTask({ assignee: "user", is_done: false })}
        onOpen={onOpen}
      />,
    );

    // Simulate the browser's selection state after a user drag-selected
    // some text inside the row but never released without dragging.
    const fakeSelection = {
      isCollapsed: false,
      toString: () => "Row task",
    } as Pick<Selection, "isCollapsed" | "toString">;
    const getSelectionSpy = vi
      .spyOn(window, "getSelection")
      .mockReturnValue(fakeSelection as Selection);

    await userEvent.click(screen.getByText("Row task"));

    expect(onOpen).not.toHaveBeenCalled();
    getSelectionSpy.mockRestore();
  });

  it("shows the next scheduled time prominently on routines, cadence as caption", () => {
    render(
      <TaskRow
        task={makeTask({
          assignee: "assistant",
          kind: "routine",
          state: "up_next",
          interval_unit: "week",
          interval_count: 1,
          do_at: "2099-06-10T09:00:00Z",
        })}
        onOpen={vi.fn()}
      />,
    );
    const block = screen.getByTestId("task-row-routine");
    // The do_at-derived "next run" string is the loud line; "Weekly" is the
    // muted caption beneath it.
    expect(block).toHaveTextContent(/Weekly/);
    expect(block.textContent ?? "").toMatch(/\d{1,2}:\d{2}/);
  });

  it("renders a labelled Stalled token + tooltip (not a bare ring)", () => {
    const { container } = render(
      <TaskRow
        task={makeTask({ assignee: "assistant", is_done: false })}
        onOpen={vi.fn()}
        isStalled
        assistantName="Nix"
      />,
    );
    const token = container.querySelector('[data-variant="stalled"]');
    expect(token).toBeInTheDocument();
    expect(token).toHaveTextContent("Stalled");
    const row = container.querySelector('[role="button"]');
    expect(row?.getAttribute("title")).toMatch(/Nix stalled/i);
  });

  it("renders a labelled 'Error — retrying' token when assignee=assistant", () => {
    const { container } = render(
      <TaskRow
        task={makeTask({ assignee: "assistant", is_done: false })}
        onOpen={vi.fn()}
        isErrored
      />,
    );
    const token = container.querySelector('[data-variant="errored"]');
    expect(token).toBeInTheDocument();
    const row = container.querySelector('[role="button"]');
    expect(row?.getAttribute("title")).toMatch(/backing off and retrying/i);
    expect(screen.getByText(/Error — retrying/)).toBeInTheDocument();
  });

  it("renders 'Error — paused' token + tooltip when assignee=user (post-handoff)", () => {
    const { container } = render(
      <TaskRow
        task={makeTask({ assignee: "user", is_done: false })}
        onOpen={vi.fn()}
        isErrored
      />,
    );
    const token = container.querySelector('[data-variant="errored"]');
    expect(token).toBeInTheDocument();
    const row = container.querySelector('[role="button"]');
    expect(row?.getAttribute("title")).toMatch(/paused this task after 3 errors/i);
    expect(screen.getByText(/Error — paused/)).toBeInTheDocument();
  });

  it("prefers the live token over stalled when both isLive and isStalled", () => {
    const { container } = render(
      <TaskRow
        task={makeTask({ assignee: "assistant", is_done: false })}
        onOpen={vi.fn()}
        isLive
        isStalled
      />,
    );
    expect(container.querySelector('[data-variant="live"]')).toBeInTheDocument();
    expect(
      container.querySelector('[data-variant="stalled"]'),
    ).not.toBeInTheDocument();
  });

  it("avatar is the reassign control: 'assign to me' on agent tasks", async () => {
    const onChanged = vi.fn();
    const task = makeTask({ assignee: "assistant", is_done: false });
    render(
      <TaskRow
        task={task}
        onOpen={vi.fn()}
        onChanged={onChanged}
        assistantName="Nix"
      />,
    );
    const toggle = screen.getByTestId("task-row-assignee-toggle");
    expect(toggle).toHaveAttribute("aria-label", "Assign to me");
    // No separate assign buttons anymore.
    expect(
      screen.queryByTestId("task-row-assign-to-user"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("task-row-assign-to-agent"),
    ).not.toBeInTheDocument();

    await userEvent.click(toggle);
    expect(updateTaskMock).toHaveBeenCalledWith(task.id, {
      assignee: "user",
    });
  });

  it("renders a linked goal chip when present", () => {
    render(
      <TaskRow
        task={makeTask({ goal_id: 3, goal_title: "Ship goals MVP" })}
        onOpen={vi.fn()}
      />,
    );

    const chip = screen.getByTestId("task-row-goal-chip");
    expect(chip).toHaveTextContent("Ship goals MVP");
  });

  it("fires onAfterToggleDone after a user-initiated checkoff", async () => {
    const onAfterToggleDone = vi.fn();
    const task = makeTask({ assignee: "user", is_done: false });
    render(
      <TaskRow
        task={task}
        onOpen={vi.fn()}
        onAfterToggleDone={onAfterToggleDone}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: /mark as done/i }),
    );
    expect(onAfterToggleDone).toHaveBeenCalledTimes(1);
    expect(onAfterToggleDone).toHaveBeenCalledWith(task, true);
  });

  it("shows the completion time on done rows", () => {
    render(
      <TaskRow
        task={makeTask({
          is_done: true,
          completed_at: new Date(Date.now() - 60_000).toISOString(),
        })}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByTestId("task-row-completed-at")).toBeInTheDocument();
  });

  it("avatar reassigns a user task to the agent", async () => {
    const onChanged = vi.fn();
    const task = makeTask({ assignee: "user" });
    render(
      <TaskRow
        task={task}
        onOpen={vi.fn()}
        onChanged={onChanged}
        assistantName="Nix"
      />,
    );
    const toggle = screen.getByTestId("task-row-assignee-toggle");
    expect(toggle).toHaveAttribute("aria-label", "Assign to Nix");
    await userEvent.click(toggle);
    expect(updateTaskMock).toHaveBeenCalledWith(task.id, {
      assignee: "assistant",
    });
    expect(onChanged).toHaveBeenCalled();
  });

  it("agent-assigned scheduled row exposes a Run-now quick action", async () => {
    const task = makeTask({
      assignee: "assistant",
      do_at: "2099-04-27T14:30:00Z",
      kind: "scheduled-job",
      state: "up_next",
    });
    render(<TaskRow task={task} onOpen={vi.fn()} />);
    await userEvent.click(screen.getByTestId("task-row-run-now"));
    expect(runTaskNowMock).toHaveBeenCalledWith(task.id);
  });

  it("hides the Run-now quick action on done rows", () => {
    render(
      <TaskRow
        task={makeTask({ assignee: "user", is_done: true })}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("task-row-run-now")).not.toBeInTheDocument();
  });

});

describe("TaskRow — two-line layout & persistent affordances", () => {
  it("title is its own clamped node, not single-line truncated", () => {
    render(
      <TaskRow
        task={makeTask({
          title:
            "A very long task title that would previously be cut off to a sliver because metadata and time competed for the same single row",
        })}
        onOpen={vi.fn()}
      />,
    );
    const title = screen.getByTestId("task-row-title");
    expect(title.className).toContain("line-clamp-2");
    expect(title.className).not.toContain("truncate");
    expect(title).toHaveTextContent(/previously be cut off/);
  });

  it("right-meta sits in a meta row beneath the title", () => {
    render(
      <TaskRow
        task={makeTask({
          is_done: true,
          completed_at: "2026-05-01T10:00:00Z",
        })}
        onOpen={vi.fn()}
      />,
    );
    const meta = screen.getByTestId("task-row-meta");
    // Done task surfaces its completed-at inside the meta row.
    expect(meta).toContainElement(
      screen.getByTestId("task-row-completed-at"),
    );
  });

  it("no empty meta row for a bare todo (no phantom gap)", () => {
    render(<TaskRow task={makeTask()} onOpen={vi.fn()} />);
    expect(screen.queryByTestId("task-row-meta")).not.toBeInTheDocument();
  });

  it("affordances are present without hover (not opacity-0 gated)", () => {
    render(
      <TaskRow
        task={makeTask({
          assignee: "assistant",
          do_at: "2099-04-27T14:30:00Z",
          kind: "scheduled-job",
          state: "up_next",
        })}
        onOpen={vi.fn()}
      />,
    );
    const toggle = screen.getByTestId("task-row-assignee-toggle");
    const runNow = screen.getByTestId("task-row-run-now");
    expect(toggle).toBeInTheDocument();
    expect(runNow).toBeInTheDocument();
    // Right-cluster wrapper must not hide actions behind hover opacity.
    expect(runNow.parentElement?.className ?? "").not.toContain("opacity-0");
  });
});
