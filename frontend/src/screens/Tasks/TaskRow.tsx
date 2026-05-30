import { ArrowLeftRight, Play, Target } from "lucide-react";
import { useState } from "react";

import {
  IconCaret,
  IconCheck,
  IconClock,
  IconRepeat,
  IconRobot,
  IconUser,
} from "@/shell/icons";
import { cn } from "@/lib/utils";

import { formatCompletedAt, formatDoAt, formatInterval } from "./format";
import { runTaskNow, updateTask, type Task } from "./tasksApi";

type TaskRowProps = {
  task: Task;
  onOpen: () => void;
  onChanged?: () => void;
  /** Fires after the row checkbox toggles `is_done`. Parent can show an undo toast. */
  onAfterToggleDone?: (task: Task, nowDone: boolean) => void;
  isLive?: boolean;
  isStalled?: boolean;
  isErrored?: boolean;
  assistantName?: string;
};

export function TaskRow({
  task,
  onOpen,
  onChanged,
  onAfterToggleDone,
  isLive = false,
  isStalled = false,
  isErrored = false,
  assistantName = "Assistant",
}: TaskRowProps) {
  const [pending, setPending] = useState(false);
  const isAssistant = task.assignee === "assistant";
  const isRunning = isAssistant && !task.is_done;
  const showLive = isRunning && isLive;
  const showStalled = !showLive && !task.is_done && isStalled;
  const showErrored = !showLive && !showStalled && !task.is_done && isErrored;
  // After 3 consecutive errors the runner hands the task back to the user
  // — so an errored task whose assignee is the user is paused, not retrying.
  const erroredPaused = showErrored && task.assignee === "user";
  let errorLabel: string | null = null;
  if (showErrored) errorLabel = erroredPaused ? "Error — paused" : "Error — retrying";
  let rowTitle: string | undefined;
  if (showStalled) {
    rowTitle = `${assistantName} stalled — will retry on next wake.`;
  } else if (showErrored) {
    rowTitle = erroredPaused
      ? `${assistantName} paused this task after 3 errors. Reassign it to retry.`
      : `${assistantName} hit an error — backing off and retrying.`;
  }

  async function handleToggleDone(e: React.MouseEvent) {
    e.stopPropagation();
    if (pending) return;
    setPending(true);
    const nextDone = !task.is_done;
    try {
      await updateTask(task.id, { is_done: nextDone });
      onChanged?.();
      // Notify the parent after the update lands so it can show an undo
      // toast on user-initiated check-offs (only this code path).
      onAfterToggleDone?.(task, nextDone);
    } finally {
      setPending(false);
    }
  }

  async function handleAssignToAgent(e: React.MouseEvent) {
    e.stopPropagation();
    if (pending) return;
    setPending(true);
    try {
      await updateTask(task.id, { assignee: "assistant" });
      onChanged?.();
    } finally {
      setPending(false);
    }
  }

  async function handleAssignToUser(e: React.MouseEvent) {
    e.stopPropagation();
    if (pending) return;
    setPending(true);
    try {
      await updateTask(task.id, { assignee: "user" });
      onChanged?.();
    } finally {
      setPending(false);
    }
  }

  async function handleRunNow(e: React.MouseEvent) {
    e.stopPropagation();
    if (pending) return;
    setPending(true);
    try {
      await runTaskNow(task.id);
      onChanged?.();
    } finally {
      setPending(false);
    }
  }

  function handleClick() {
    // Don't navigate if the user just finished a text selection —
    // selecting a phrase in a row is a common copy-paste flow and
    // should never count as an "open" intent.
    const selection = typeof window !== "undefined" ? window.getSelection() : null;
    if (selection && !selection.isCollapsed && selection.toString().length > 0) {
      return;
    }
    onOpen();
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onOpen();
    }
  }

  // Runner state is shown as a labelled token in the meta row (the old
  // colour-only avatar ring was undiscoverable). Precedence:
  // live > stalled > errored.
  let stateToken: React.ReactNode = null;
  if (showLive) {
    stateToken = (
      <span
        data-variant="live"
        className="flex shrink-0 items-center gap-1 rounded-full bg-life-accent-soft px-2 py-0.5 text-[11px] font-medium text-life-accent"
      >
        <span
          aria-hidden
          className="h-1.5 w-1.5 rounded-full bg-life-accent animate-[pulseRun_1.4s_infinite]"
        />
        Live
      </span>
    );
  } else if (showStalled) {
    stateToken = (
      <span
        data-variant="stalled"
        className="flex shrink-0 items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-700 dark:bg-amber-500/15 dark:text-amber-300"
      >
        Stalled
      </span>
    );
  } else if (showErrored) {
    stateToken = (
      <span
        data-variant="errored"
        className="flex shrink-0 items-center gap-1 rounded-full bg-rose-100 px-2 py-0.5 text-[11px] font-medium text-rose-700 dark:bg-rose-500/15 dark:text-rose-300"
      >
        {errorLabel}
      </span>
    );
  }

  // Call RightLabel as a function (no hooks) so a null result is
  // detectable — an always-truthy element would render an empty meta
  // row for plain todos (the phantom-gap bug, again).
  const timeNode = RightLabel({ task });
  const showGoal = task.goal_id !== null && task.goal_title !== null;
  const hasMeta = showGoal || stateToken !== null || timeNode !== null;
  // Live-running tasks: the agent is mid-step. Checking off is still
  // allowed (it stops on next notice) but the live one is greyed to
  // discourage racing the runner.
  const checkDisabled = pending || showLive;

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      title={rowTitle}
      className="group flex w-full items-start gap-3 px-2 py-2.5 text-left transition-colors hover:bg-life-card focus:outline-none focus-visible:bg-life-card"
    >
      <button
        type="button"
        onClick={handleToggleDone}
        aria-pressed={task.is_done}
        aria-label={task.is_done ? "Mark as not done" : "Mark as done"}
        disabled={checkDisabled}
        title={
          showLive
            ? `${assistantName} is mid-step — finishes the current step before stopping`
            : undefined
        }
        className={cn(
          "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border transition-colors",
          task.is_done
            ? "border-life-done bg-life-done text-white"
            : "border-life-ink-3/40 text-transparent hover:border-life-accent hover:text-life-accent",
          showLive && "cursor-not-allowed opacity-40",
        )}
      >
        <IconCheck className="h-3.5 w-3.5" />
      </button>

      {/* The owner avatar IS the reassign control: tap to hand the task
          to the assistant / take it back. No separate assign button. */}
      <button
        type="button"
        onClick={isAssistant ? handleAssignToUser : handleAssignToAgent}
        disabled={pending}
        data-testid="task-row-assignee-toggle"
        aria-label={
          isAssistant ? "Assign to me" : `Assign to ${assistantName}`
        }
        title={
          isAssistant
            ? "Assigned to assistant — tap to take it back"
            : `Assigned to you — tap to hand to ${assistantName}`
        }
        className={cn(
          "relative mt-0.5 flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-full ring-1 transition-all hover:ring-2 hover:ring-life-accent/50",
          isAssistant
            ? "bg-life-accent-soft text-life-accent ring-life-accent/30"
            : "bg-life-line/60 text-life-ink-2 ring-life-ink-3/25",
        )}
      >
        {isAssistant ? (
          <IconRobot className="h-4 w-4" />
        ) : (
          <IconUser className="h-4 w-4" />
        )}
        {/* Persistent swap badge so the avatar reads as a toggle, not a
            static status icon. */}
        <span
          aria-hidden
          className="absolute -right-1 -bottom-1 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-life-card text-life-ink-3 ring-1 ring-life-line transition-colors group-hover:text-life-accent"
        >
          <ArrowLeftRight className="h-2.5 w-2.5" />
        </span>
      </button>

      {/* Two lines: title (up to 2, never clipped to one) then a meta
          row — goal/state/time context underneath. */}
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <span
          data-testid="task-row-title"
          className={cn(
            "line-clamp-2 break-words text-[15px] font-medium",
            task.is_done ? "text-life-ink-3 line-through" : "text-life-ink",
          )}
        >
          {task.title}
        </span>
        {hasMeta && (
          <div
            data-testid="task-row-meta"
            className="flex items-center gap-2 text-[12px] text-life-ink-3"
          >
            {showGoal && (
              <span
                data-testid="task-row-goal-chip"
                className="inline-flex min-w-0 max-w-[14rem] shrink items-center gap-1 rounded-full border border-life-line bg-life-card px-1.5 py-0.5 text-[11px] font-medium text-life-ink-3"
                title={`Goal: ${task.goal_title}`}
              >
                <Target className="h-3 w-3 shrink-0" />
                <span className="truncate">{task.goal_title}</span>
              </span>
            )}
            {(stateToken !== null || timeNode !== null) && (
              <span className="ml-auto flex shrink-0 items-center gap-2">
                {stateToken}
                {timeNode}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Actions right-aligned on the title's baseline so they line up
          with the left check-off. Persistent (not hover-only) faint
          affordances — no mystery empty gap, openable on touch. */}
      <div className="mt-0.5 flex shrink-0 items-center gap-1 text-life-ink-3">
        <RowQuickActions task={task} pending={pending} onRunNow={handleRunNow} />
        <IconCaret />
      </div>
    </div>
  );
}

function RowQuickActions({
  task,
  pending,
  onRunNow,
}: {
  task: Task;
  pending: boolean;
  onRunNow: (e: React.MouseEvent) => void;
}) {
  if (task.is_done) return null;
  // Reassignment now lives on the owner avatar. The only row action
  // left is Run-now, for assistant tasks sitting on a future do_at.
  const showRunNow = task.assignee === "assistant" && task.do_at !== null;
  if (!showRunNow) return null;
  return (
    <button
      type="button"
      onClick={onRunNow}
      disabled={pending}
      data-testid="task-row-run-now"
      aria-label="Run now"
      title="Run now"
      className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-life-line bg-life-card text-life-ink-3 hover:border-life-accent hover:text-life-accent"
    >
      <Play className="h-3.5 w-3.5" />
    </button>
  );
}

function RightLabel({ task }: { task: Task }) {
  if (task.is_done) {
    // Surface when the task was completed — makes accidental checkoffs easy
    // to spot ("wait, I marked that done two minutes ago") and gives the
    // Done bucket some auditability.
    if (task.completed_at) {
      return (
        <span
          data-testid="task-row-completed-at"
          className="flex shrink-0 items-center gap-1 text-[12px] text-life-ink-3"
        >
          <IconCheck className="h-3 w-3" />
          {formatCompletedAt(task.completed_at)}
        </span>
      );
    }
    return null;
  }

  // Routines: lead with the next scheduled time when we have one; cadence
  // (Weekly / Every 2 days / …) drops to a quieter caption underneath.
  // Catching attention with "Today 09:00" beats "Weekly" for a glance.
  if (
    task.kind === "routine"
    && task.interval_unit
    && task.interval_count !== null
  ) {
    const cadence = formatInterval(task.interval_unit, task.interval_count);
    if (task.do_at) {
      // Single line: "next-run · cadence" — the stacked two-line form
      // wrapped badly inside the meta row.
      return (
        <span
          data-testid="task-row-routine"
          className="flex shrink-0 items-center gap-1 text-[12px] text-life-ink-3"
        >
          <IconClock className="h-3 w-3" />
          <span className="text-life-ink-2">{formatDoAt(task.do_at)}</span>
          <span aria-hidden>·</span>
          <IconRepeat className="h-3 w-3" />
          {cadence}
        </span>
      );
    }
    return (
      <span className="flex shrink-0 items-center gap-1 text-[12px] text-life-ink-3">
        <IconRepeat className="h-3 w-3" />
        {cadence}
      </span>
    );
  }

  // Deadlines: show due_at.
  if (task.kind === "deadline" && task.due_at) {
    return (
      <span className="flex shrink-0 items-center gap-1 text-[12px] text-life-ink-3">
        <IconClock className="h-3 w-3" />
        Due {formatDoAt(task.due_at)}
      </span>
    );
  }

  // Scheduled todo / scheduled job: show do_at if still future.
  if (
    (task.kind === "scheduled-todo" || task.kind === "scheduled-job")
    && task.do_at
    && task.state === "up_next"
  ) {
    return (
      <span className="flex shrink-0 items-center gap-1 text-[12px] text-life-ink-3">
        <IconClock className="h-3 w-3" />
        {formatDoAt(task.do_at)}
      </span>
    );
  }

  return null;
}
