import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { EditTaskSheet } from "./EditTaskSheet";
import {
  CompactTaskHeader,
  DescriptionSection,
  TaskMetadataSummary,
} from "./TaskDetailPage";
import type { Task } from "./tasksApi";

vi.mock("@/shell/identity", () => ({
  useIdentity: () => ({
    assistantName: "Nix",
    isOnboarding: false,
    onboardingState: "done",
    refetch: vi.fn(),
  }),
}));

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 1,
    title: "Test task",
    description: "Test description",
    is_done: false,
    assignee: "user",
    chat_session_id: 10,
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

function renderHeader(
  task: Task,
  onPatch = vi.fn().mockResolvedValue(undefined),
  onRunNow = vi.fn().mockResolvedValue(undefined),
) {
  const onBack = vi.fn();
  const onOpenSourceChat = vi.fn();
  const onEdit = vi.fn();
  render(
    <CompactTaskHeader
      task={task}
      isLive={false}
      onBack={onBack}
      onOpenSourceChat={onOpenSourceChat}
      onPatch={onPatch}
      onEdit={onEdit}
      onRunNow={onRunNow}
    />,
  );
  return { onPatch, onBack, onOpenSourceChat, onEdit, onRunNow };
}

describe("CompactTaskHeader — running task (assignee=assistant && !is_done)", () => {
  const runningTask = makeTask({
    assignee: "assistant",
    is_done: false,
    title: "X",
    kind: "job",
    state: "running",
  });

  it("renders read-only title and a Take over button", () => {
    renderHeader(runningTask);

    const takeOver = screen.getByTestId("task-pause");
    expect(takeOver).toBeInTheDocument();
    expect(takeOver).toHaveTextContent("Take over");
    expect(screen.getByTestId("task-title-static")).toHaveTextContent("X");
    expect(screen.queryByTestId("task-done")).not.toBeInTheDocument();
    expect(screen.queryByTestId("task-reopen")).not.toBeInTheDocument();
  });

  it("clicking Pause patches assignee=user and nothing else", async () => {
    const { onPatch } = renderHeader(runningTask);
    await userEvent.click(screen.getByTestId("task-pause"));

    expect(onPatch).toHaveBeenCalledTimes(1);
    expect(onPatch).toHaveBeenCalledWith({ assignee: "user" });
  });

  it("Pause does not touch do_at on a recurring running task", async () => {
    const recurring = makeTask({
      assignee: "assistant",
      is_done: false,
      do_at: "2026-05-01T09:00:00Z",
      interval_unit: "week",
      interval_count: 1,
      kind: "routine",
      state: "running",
    });
    const { onPatch } = renderHeader(recurring);
    await userEvent.click(screen.getByTestId("task-pause"));

    expect(onPatch).toHaveBeenCalledWith({ assignee: "user" });
    expect(Object.keys(onPatch.mock.calls[0][0])).toEqual(["assignee"]);
  });
});

describe("CompactTaskHeader — idle task", () => {
  const idleTask = makeTask({
    assignee: "user",
    is_done: false,
    title: "Idle",
  });

  it("renders Done and Edit buttons but no Pause", () => {
    renderHeader(idleTask);

    expect(
      screen.getByRole("button", { name: /mark task done/i }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("task-edit")).toBeInTheDocument();
    expect(screen.queryByTestId("task-pause")).not.toBeInTheDocument();
  });

  it("clicking Done patches is_done=true", async () => {
    const { onPatch } = renderHeader(idleTask);
    await userEvent.click(screen.getByTestId("task-done"));
    expect(onPatch).toHaveBeenCalledWith({ is_done: true });
  });

  it("clicking Edit calls onEdit", async () => {
    const { onEdit } = renderHeader(idleTask);
    await userEvent.click(screen.getByTestId("task-edit"));
    expect(onEdit).toHaveBeenCalledTimes(1);
  });

  it("offers a one-click 'Assign to <assistant>' affordance", async () => {
    const { onPatch } = renderHeader(idleTask);
    const button = screen.getByTestId("task-assign-to-agent");
    expect(button).toHaveTextContent(/Assign to Nix/);
    await userEvent.click(button);
    expect(onPatch).toHaveBeenCalledWith({ assignee: "assistant" });
  });

  it("hides the Assign-to-agent button on done tasks", () => {
    renderHeader(makeTask({ assignee: "user", is_done: true }));
    expect(
      screen.queryByTestId("task-assign-to-agent"),
    ).not.toBeInTheDocument();
  });
});

describe("CompactTaskHeader — Run now affordance", () => {
  it("appears for scheduled assistant tasks and triggers onRunNow", async () => {
    const scheduled = makeTask({
      assignee: "assistant",
      is_done: false,
      do_at: "2099-06-10T09:00:00Z",
      kind: "scheduled-job",
      state: "up_next",
    });
    const { onRunNow } = renderHeader(scheduled);
    const button = screen.getByTestId("task-run-now");
    expect(button).toHaveTextContent(/Run now/);
    await userEvent.click(button);
    expect(onRunNow).toHaveBeenCalledTimes(1);
  });

  it("is hidden for assistant tasks without a scheduled do_at", () => {
    const alwaysOn = makeTask({
      assignee: "assistant",
      is_done: false,
      do_at: null,
      kind: "job",
      state: "running",
    });
    renderHeader(alwaysOn);
    expect(screen.queryByTestId("task-run-now")).not.toBeInTheDocument();
  });

  it("is hidden for user-assigned tasks", () => {
    renderHeader(
      makeTask({
        assignee: "user",
        is_done: false,
        do_at: "2099-06-10T09:00:00Z",
      }),
    );
    expect(screen.queryByTestId("task-run-now")).not.toBeInTheDocument();
  });
});

describe("DescriptionSection — text selection safety", () => {
  it("description body is not a button and does not open the editor on click", async () => {
    const onEdit = vi.fn();
    render(
      <DescriptionSection task={makeTask()} onEdit={onEdit} />,
    );
    const body = screen.getByTestId("task-description-static");
    expect(body.getAttribute("role")).not.toBe("button");
    await userEvent.click(body);
    expect(onEdit).not.toHaveBeenCalled();
  });
});

describe("CompactTaskHeader — done task", () => {
  const doneTask = makeTask({
    assignee: "assistant",
    is_done: true,
    kind: "job",
    state: "done",
  });

  it("renders a Reopen button instead of Done/Pause", () => {
    renderHeader(doneTask);

    expect(screen.getByTestId("task-reopen")).toBeInTheDocument();
    expect(screen.queryByTestId("task-pause")).not.toBeInTheDocument();
    expect(screen.queryByTestId("task-done")).not.toBeInTheDocument();
  });

  it("clicking Reopen patches is_done=false", async () => {
    const { onPatch } = renderHeader(doneTask);
    await userEvent.click(screen.getByTestId("task-reopen"));
    expect(onPatch).toHaveBeenCalledWith({ is_done: false });
  });
});

describe("TaskMetadataSummary", () => {
  function renderSummary(task: Task) {
    render(
      <MemoryRouter>
        <TaskMetadataSummary task={task} />
      </MemoryRouter>,
    );
  }

  it("shows assignee, do_at, due_at, recurrence and status", () => {
    const task = makeTask({
      assignee: "assistant",
      do_at: "2026-05-10T09:00:00Z",
      due_at: "2026-05-15T09:00:00Z",
      interval_unit: "week",
      interval_count: 1,
      kind: "routine",
      state: "running",
    });
    renderSummary(task);
    const summary = screen.getByTestId("task-metadata-summary");
    expect(summary).toHaveTextContent("Nix");
    expect(summary).toHaveTextContent(/Next run/i);
    expect(summary).toHaveTextContent(/Due/i);
    expect(summary).toHaveTextContent(/Weekly/i);
    expect(summary).toHaveTextContent(/Running/i);
  });

  it("falls back to 'On you' when user-assigned and not done", () => {
    renderSummary(makeTask());
    expect(screen.getByTestId("task-metadata-summary")).toHaveTextContent(
      /On you/i,
    );
  });

  it("links to the parent goal when present", () => {
    renderSummary(makeTask({ goal_id: 9, goal_title: "Ship goals MVP" }));
    const link = screen.getByRole("link", { name: "Ship goals MVP" });
    expect(link).toHaveAttribute("href", "/goals/9");
  });
});

describe("DescriptionSection", () => {
  it("shows the description text and an Edit affordance", async () => {
    const onEdit = vi.fn();
    render(
      <DescriptionSection task={makeTask()} onEdit={onEdit} />,
    );
    expect(screen.getByTestId("task-description-static")).toHaveTextContent(
      "Test description",
    );
    await userEvent.click(screen.getByTestId("task-description-edit"));
    expect(onEdit).toHaveBeenCalledTimes(1);
  });

  it("when empty, shows an 'Add a description…' button that opens the editor", async () => {
    const onEdit = vi.fn();
    render(
      <DescriptionSection
        task={makeTask({ description: null })}
        onEdit={onEdit}
      />,
    );
    expect(
      screen.queryByTestId("task-description-static"),
    ).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: /add a description/i }),
    );
    expect(onEdit).toHaveBeenCalledTimes(1);
  });
});

describe("EditTaskSheet", () => {
  it("renders title, description, and assignee/when controls when open", () => {
    render(
      <EditTaskSheet
        open
        task={makeTask()}
        onClose={vi.fn()}
        onPatch={vi.fn().mockResolvedValue(undefined)}
        onDelete={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.getByLabelText("Title")).toBeInTheDocument();
    // Description is no longer an inline textarea — it's a button that
    // opens the full-screen editor (uncramped on mobile).
    expect(
      screen.getByTestId("edit-task-description-open"),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("description-editor")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Me" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Nix" })).toBeInTheDocument();
  });

  it("opens the full-screen description editor and saves via onPatch", async () => {
    const onPatch = vi.fn().mockResolvedValue(undefined);
    render(
      <EditTaskSheet
        open
        task={makeTask({ description: "old" })}
        onClose={vi.fn()}
        onPatch={onPatch}
      />,
    );

    await userEvent.click(screen.getByTestId("edit-task-description-open"));
    const editor = await screen.findByTestId("description-editor");
    const area = within(editor).getByLabelText("Description");
    await userEvent.clear(area);
    await userEvent.type(area, "new body");
    await userEvent.click(screen.getByTestId("description-editor-save"));

    expect(onPatch).toHaveBeenCalledWith({ description: "new body" });
  });

  it("clicking a Who pill patches assignee", async () => {
    const onPatch = vi.fn().mockResolvedValue(undefined);
    render(
      <EditTaskSheet
        open
        task={makeTask()}
        onClose={vi.fn()}
        onPatch={onPatch}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Nix" }));
    expect(onPatch).toHaveBeenCalledWith({ assignee: "assistant" });
  });

  it("Delete confirms before invoking onDelete", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const onDelete = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(
      <EditTaskSheet
        open
        task={makeTask()}
        onClose={onClose}
        onPatch={vi.fn().mockResolvedValue(undefined)}
        onDelete={onDelete}
      />,
    );
    await userEvent.click(screen.getByTestId("task-delete"));
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledTimes(1);
    confirmSpy.mockRestore();
  });

  it("Delete is skipped when the user cancels confirm", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    const onDelete = vi.fn().mockResolvedValue(undefined);
    render(
      <EditTaskSheet
        open
        task={makeTask()}
        onClose={vi.fn()}
        onPatch={vi.fn().mockResolvedValue(undefined)}
        onDelete={onDelete}
      />,
    );
    await userEvent.click(screen.getByTestId("task-delete"));
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(onDelete).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });
});
