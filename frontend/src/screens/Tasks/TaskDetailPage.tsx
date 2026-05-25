import {
  ArrowLeft,
  Bot,
  CalendarClock,
  CheckCircle2,
  Pencil,
  Play,
  RotateCcw,
  Tag,
  Timer,
  User as UserIcon,
} from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { MarkdownView } from "@/components/MarkdownView";
import { Button } from "@/components/ui/button";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useGoBack } from "@/lib/useGoBack";
import { cn } from "@/lib/utils";
import { labelSlugDisplay } from "@/screens/Labels/labelDisplay";
import { useIdentity } from "@/shell/identity";

import { getChatChannel } from "../Chat/chatChannel";
import { getChatMessages } from "../Chat/chatApi";
import type { WireMessage } from "../Chat/convertChatMessage";
import { DescriptionEditor } from "./DescriptionEditor";
import { EditTaskSheet } from "./EditTaskSheet";
import { TaskActivityThread } from "./TaskActivityThread";
import { formatDoAt, formatInterval, KIND_LABEL } from "./format";
import {
  deleteTask,
  fetchTaskActivity,
  getTask,
  runTaskNow,
  updateTask,
  type Task,
  type TaskUpdate,
} from "./tasksApi";

const ACTIVITY_POLL_MS = 3000;

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; task: Task; initialMessages: WireMessage[] }
  | { kind: "error"; message: string };

export function TaskDetailPage() {
  const params = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const goBack = useGoBack("/tasks");
  const taskId = params.taskId ? Number(params.taskId) : NaN;
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  const reload = useCallback(async () => {
    if (Number.isNaN(taskId)) {
      setState({ kind: "error", message: "Invalid task id" });
      return;
    }
    try {
      const task = await getTask(taskId);
      const messages = task.chat_session_id
        ? await getChatMessages(task.chat_session_id)
        : [];
      setState({ kind: "ready", task, initialMessages: messages });
    } catch (e) {
      setState({
        kind: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    }
  }, [taskId]);

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    (async () => {
      if (!cancelled) await reload();
    })();
    return () => {
      cancelled = true;
    };
  }, [reload]);

  // Keep the task chrome fresh from the same single channel as the
  // activity thread. Task rows now publish keyed upserts; runner_finished
  // remains a narrow fallback for older/indirect write paths.
  useEffect(() => {
    if (state.kind !== "ready" || !state.task.chat_session_id) return;
    const chatSessionId = state.task.chat_session_id;
    const channel = getChatChannel();
    const remove = channel.addListener((event) => {
      if (event.session_id !== chatSessionId) return;
      if (event.type === "task_upsert") {
        const task = event.task as Task | undefined;
        if (!task || task.id !== taskId) return;
        setState((s) => (s.kind === "ready" ? { ...s, task } : s));
        return;
      }
      if (event.type === "task_delete" && event.task_id === taskId) {
        navigate("/tasks");
        return;
      }
      if (event.type !== "runner_finished") return;
      getTask(taskId)
        .then((t) => {
          setState((s) => (s.kind === "ready" ? { ...s, task: t } : s));
        })
        .catch(() => {
          /* keep stale task header on transient errors */
        });
    });
    return remove;
  }, [state.kind === "ready" ? state.task.chat_session_id : null, taskId, navigate]);

  const patchTask = useCallback(
    async (patch: TaskUpdate) => {
      if (state.kind !== "ready") return;
      const next = await updateTask(taskId, patch);
      setState((s) => (s.kind === "ready" ? { ...s, task: next } : s));
    },
    [state.kind, taskId],
  );

  const handleDelete = useCallback(async () => {
    if (state.kind !== "ready") return;
    await deleteTask(taskId);
    navigate("/tasks");
  }, [state.kind, taskId, navigate]);

  const handleRunNow = useCallback(async () => {
    if (state.kind !== "ready") return;
    const next = await runTaskNow(taskId);
    setState((s) => (s.kind === "ready" ? { ...s, task: next } : s));
  }, [state.kind, taskId]);

  const sessionId = state.kind === "ready" ? state.task.chat_session_id : null;
  const [isLive, setIsLive] = useState(false);
  useEffect(() => {
    if (sessionId == null) {
      setIsLive(false);
      return;
    }
    let cancelled = false;
    let interval: number | null = null;

    const tick = async () => {
      try {
        const a = await fetchTaskActivity();
        if (cancelled) return;
        setIsLive(a.active_session_ids.includes(sessionId));
      } catch {
        // Ignore transient errors.
      }
    };

    const start = () => {
      if (interval !== null) return;
      void tick();
      interval = window.setInterval(tick, ACTIVITY_POLL_MS);
    };
    const stop = () => {
      if (interval !== null) {
        window.clearInterval(interval);
        interval = null;
      }
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") start();
      else stop();
    };

    onVisibility();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      cancelled = true;
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [sessionId]);

  if (state.kind === "loading") {
    return (
      <div className="flex h-full items-center justify-center text-sm text-life-ink-3">
        Loading…
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
        <div className="text-sm text-red-500">
          Couldn't load task: {state.message}
        </div>
        <button
          type="button"
          onClick={() => navigate("/tasks")}
          className="text-xs text-life-ink-3 underline"
        >
          Back to tasks
        </button>
      </div>
    );
  }

  return (
    <TaskDetailShell
      task={state.task}
      initialMessages={state.initialMessages}
      isLive={isLive}
      onBack={goBack}
      // Main chat is the only chat route; the session id is implicit
      // server-side. Navigating to `/chat/${sid}` falls through to the
      // catch-all redirect and pollutes history.
      onOpenSourceChat={() => navigate("/chat")}
      onPatch={patchTask}
      onDelete={handleDelete}
      onRunNow={handleRunNow}
    />
  );
}

export function TaskDetailShell({
  task,
  initialMessages,
  isLive,
  onBack,
  onOpenSourceChat,
  onPatch,
  onDelete,
  onRunNow,
}: {
  task: Task;
  initialMessages: WireMessage[];
  isLive: boolean;
  onBack: () => void;
  onOpenSourceChat: (sessionId: number) => void;
  onPatch: (patch: TaskUpdate) => Promise<void>;
  onDelete: () => Promise<void>;
  onRunNow: () => Promise<void>;
}) {
  const [editOpen, setEditOpen] = useState(false);
  const [descEditorOpen, setDescEditorOpen] = useState(false);

  const sid = task.chat_session_id;

  const before = (
    <>
      <TaskMetadataSummary task={task} />
      <DescriptionSection task={task} onEdit={() => setDescEditorOpen(true)} />
    </>
  );
  const heading = (
    <h2
      id={`task-${task.id}-activity-heading`}
      className="text-[10px] font-bold uppercase tracking-[0.6px] text-life-ink-3"
    >
      Activity
    </h2>
  );

  return (
    <TooltipProvider>
      <div className="flex h-full min-h-0 flex-col bg-life-bg">
        <CompactTaskHeader
          task={task}
          isLive={isLive}
          onBack={onBack}
          onOpenSourceChat={onOpenSourceChat}
          onPatch={onPatch}
          onEdit={() => setEditOpen(true)}
          onRunNow={onRunNow}
        />
        <div className="flex min-h-0 flex-1 flex-col">
          {sid ? (
            <TaskActivityThread
              key={sid}
              task={task}
              sessionId={sid}
              initialMessages={initialMessages}
              before={before}
              heading={heading}
            />
          ) : (
            <NoSessionFallback before={before} />
          )}
        </div>
        <EditTaskSheet
          open={editOpen}
          task={task}
          onClose={() => setEditOpen(false)}
          onPatch={onPatch}
          onDelete={onDelete}
        />
        <DescriptionEditor
          open={descEditorOpen}
          initialValue={task.description ?? ""}
          onSave={(v) => onPatch({ description: v })}
          onClose={() => setDescEditorOpen(false)}
        />
      </div>
    </TooltipProvider>
  );
}

function NoSessionFallback({ before }: { before: ReactNode }) {
  return (
    <div className="flex-1 overflow-y-auto">
      <div
        className="mx-auto flex w-full max-w-(--task-detail-max-width) flex-col gap-4 px-4 pt-4 sm:px-5"
        style={{ ["--task-detail-max-width" as string]: "44rem" }}
      >
        {before}
        <p className="py-6 text-center text-sm text-life-ink-3">
          This task has no chat session.
        </p>
      </div>
    </div>
  );
}

export function CompactTaskHeader({
  task,
  isLive,
  onBack,
  onOpenSourceChat,
  onPatch,
  onEdit,
  onRunNow,
}: {
  task: Task;
  isLive: boolean;
  onBack: () => void;
  onOpenSourceChat: (sessionId: number) => void;
  onPatch: (patch: TaskUpdate) => Promise<void>;
  onEdit: () => void;
  onRunNow?: () => Promise<void>;
}) {
  const { assistantName } = useIdentity();
  const isRunning = task.assignee === "assistant" && !task.is_done;
  const showLive = isRunning && isLive;
  const sourceTitle = task.source_chat_title?.trim() || "earlier chat";
  // Run-now applies only to assistant tasks that are sitting on a future
  // schedule (or due-today). For "always running" jobs without a do_at,
  // the runner is already in charge — there is nothing to nudge.
  // Run-now is relevant when the assistant owns a task but is sitting on
  // a future `do_at` (scheduled run / scheduled reminder / next routine
  // cycle). When the agent is already mid-turn, the button would be a
  // no-op, so hide it while `showLive`.
  const canRunNow = isRunning && !showLive && task.do_at !== null;
  // One-click escalation: user-assigned tasks get a button that hands the
  // task to the assistant. Done tasks don't need a delegate action.
  const canAssignToAgent = task.assignee === "user" && !task.is_done;

  const togglePause = async () => {
    await onPatch({ assignee: "user" });
  };
  const toggleDone = async () => {
    await onPatch({ is_done: !task.is_done });
  };
  const assignToAgent = async () => {
    await onPatch({ assignee: "assistant" });
  };

  return (
    <header className="border-b border-life-line bg-life-card px-4 pt-3 pb-3 sm:px-5">
      <div className="mx-auto flex w-full max-w-(--task-detail-max-width) flex-col gap-2"
        style={{ ["--task-detail-max-width" as string]: "44rem" }}
      >
        <div className="flex items-center gap-1.5 text-xs text-life-ink-3">
          <button
            type="button"
            onClick={onBack}
            aria-label="Back to tasks"
            className="-ml-1 inline-flex items-center gap-1 rounded px-1 py-0.5 hover:bg-life-bg"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Tasks
          </button>
          {task.source_chat_session_id ? (
            <>
              <span aria-hidden>·</span>
              <button
                type="button"
                onClick={() =>
                  onOpenSourceChat(task.source_chat_session_id as number)
                }
                className="truncate rounded px-1 py-0.5 hover:bg-life-bg"
              >
                from chat <span className="italic">"{sourceTitle}"</span>
              </button>
            </>
          ) : null}
          <span className="ml-auto inline-block rounded-full border border-life-line bg-life-bg px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.6px] text-life-ink-3">
            {KIND_LABEL[task.kind]}
          </span>
        </div>

        <div className="flex flex-col gap-2">
          <h1
            data-testid="task-title-static"
            className={cn(
              "font-serif text-[22px] leading-tight",
              task.is_done ? "text-life-ink-3 line-through" : "text-life-ink",
            )}
          >
            {task.title}
          </h1>
          <div className="flex flex-wrap items-center gap-1.5">
            {showLive && (
              <span className="flex items-center gap-1.5 rounded-full bg-life-accent-soft px-2 py-1 text-[11px] font-medium text-life-accent">
                <span
                  aria-hidden
                  className="h-1.5 w-1.5 rounded-full bg-life-accent animate-[pulseRun_1.4s_infinite]"
                />
                Live
              </span>
            )}
            {canRunNow && onRunNow ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                data-testid="task-run-now"
                onClick={() => void onRunNow()}
                aria-label="Run task now"
                className="rounded-full"
              >
                <Play className="h-3.5 w-3.5" />
                Run now
              </Button>
            ) : null}
            {canAssignToAgent ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                data-testid="task-assign-to-agent"
                onClick={() => void assignToAgent()}
                aria-label={`Assign task to ${assistantName}`}
                className="rounded-full"
              >
                <Bot className="h-3.5 w-3.5" />
                Assign to {assistantName}
              </Button>
            ) : null}
            {isRunning ? (
              <Button
                type="button"
                size="sm"
                data-testid="task-pause"
                onClick={() => void togglePause()}
                aria-label="Take over from assistant"
                title={`Hands the task back to you. ${assistantName} stops after the current step finishes.`}
                className="rounded-full"
              >
                Take over
              </Button>
            ) : task.is_done ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                data-testid="task-reopen"
                onClick={() => void toggleDone()}
                className="rounded-full"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                Reopen
              </Button>
            ) : (
              <Button
                type="button"
                size="sm"
                data-testid="task-done"
                onClick={() => void toggleDone()}
                aria-label="Mark task done"
                className="rounded-full"
              >
                <CheckCircle2 className="h-3.5 w-3.5" />
                Done
              </Button>
            )}
            <Button
              type="button"
              size="icon-sm"
              variant="outline"
              data-testid="task-edit"
              onClick={onEdit}
              aria-label="Edit task"
              className="rounded-full"
            >
              <Pencil className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      </div>
    </header>
  );
}

export function TaskMetadataSummary({ task }: { task: Task }) {
  const { assistantName } = useIdentity();
  const items: { icon: ReactNode; label: string; value: ReactNode }[] = [];

  if (task.labels.length > 0) {
    items.push({
      icon: <Tag className="h-3.5 w-3.5" />,
      label: "Labels",
      value: (
        <span
          data-testid="task-detail-labels"
          className="flex flex-wrap items-center gap-1"
        >
          {task.labels.map((slug) => (
            <span
              key={slug}
              data-testid="task-detail-label-chip"
              className="rounded-full border border-life-line bg-life-bg px-1.5 py-0.5 text-[11px] font-medium text-life-ink-2"
            >
              {labelSlugDisplay(slug)}
            </span>
          ))}
        </span>
      ),
    });
  }

  items.push({
    icon:
      task.assignee === "assistant" ? (
        <Bot className="h-3.5 w-3.5" />
      ) : (
        <UserIcon className="h-3.5 w-3.5" />
    ),
    label: "Assignee",
    value: task.assignee === "assistant" ? assistantName : "You",
  });

  if (task.do_at) {
    items.push({
      icon: <CalendarClock className="h-3.5 w-3.5" />,
      label: task.interval_unit ? "Next run" : "Start",
      value: formatDoAt(task.do_at),
    });
  }

  if (task.due_at) {
    items.push({
      icon: <Timer className="h-3.5 w-3.5" />,
      label: "Due",
      value: formatDoAt(task.due_at),
    });
  }

  if (task.interval_unit && task.interval_count != null) {
    items.push({
      icon: <RotateCcw className="h-3.5 w-3.5" />,
      label: "Repeats",
      value: formatInterval(task.interval_unit, task.interval_count),
    });
  }

  items.push({
    icon: <CheckCircle2 className="h-3.5 w-3.5" />,
    label: "Status",
    value: stateLabel(task),
  });

  // Once a task is done, surface *when* it was completed. Makes accidental
  // checkoffs easy to spot, and helps when you're looking back ("did I
  // already finish this last Tuesday?").
  if (task.is_done && task.completed_at) {
    items.push({
      icon: <CheckCircle2 className="h-3.5 w-3.5" />,
      label: "Completed",
      value: formatDoAt(task.completed_at),
    });
  }

  return (
    <dl
      data-testid="task-metadata-summary"
      className="flex flex-wrap gap-x-4 gap-y-1.5 rounded-xl border border-life-line bg-life-card px-3 py-2 text-[12px] text-life-ink-2"
    >
      {items.map((it) => (
        <div key={it.label} className="flex items-center gap-1.5">
          <span className="text-life-ink-3">{it.icon}</span>
          <span className="text-life-ink-3">{it.label}:</span>
          <span className="text-life-ink">{it.value}</span>
        </div>
      ))}
    </dl>
  );
}

function stateLabel(task: Task): string {
  if (task.is_done) return "Done";
  if (task.assignee === "assistant") return "Running";
  return "On you";
}

export function DescriptionSection({
  task,
  onEdit,
}: {
  task: Task;
  onEdit: () => void;
}) {
  const desc = task.description?.trim() ?? "";
  const hasDesc = desc.length > 0;
  return (
    <section
      aria-labelledby={`task-${task.id}-description-heading`}
      className="flex flex-col gap-1.5"
    >
      <div className="flex items-center justify-between">
        <h2
          id={`task-${task.id}-description-heading`}
          className="text-[10px] font-bold uppercase tracking-[0.6px] text-life-ink-3"
        >
          Description
        </h2>
        <button
          type="button"
          onClick={onEdit}
          data-testid="task-description-edit"
          className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] text-life-ink-3 hover:bg-life-card hover:text-life-ink-2"
        >
          <Pencil className="h-3 w-3" />
          Edit
        </button>
      </div>
      {hasDesc ? (
        <div
          data-testid="task-description-static"
          className="rounded-xl border border-life-line bg-life-card px-3 py-2.5 text-[13px] leading-relaxed text-life-ink-2 select-text"
        >
          <MarkdownView source={desc} />
        </div>
      ) : (
        <button
          type="button"
          onClick={onEdit}
          className="rounded-xl border border-dashed border-life-line bg-life-card px-3 py-2.5 text-left text-[13px] text-life-ink-3 hover:border-life-accent/40"
        >
          Add a description…
        </button>
      )}
    </section>
  );
}
