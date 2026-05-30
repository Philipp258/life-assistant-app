import {
  ArrowLeft,
  CheckCircle2,
  Circle,
  ListTodo,
  Plus,
  RotateCcw,
  Target,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { MarkdownView } from "@/components/MarkdownView";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useGoBack } from "@/lib/useGoBack";
import { cn } from "@/lib/utils";
import { TaskRow } from "@/screens/Tasks/TaskRow";
import { formatDoAt } from "@/screens/Tasks/format";
import { createTask, type Assignee } from "@/screens/Tasks/tasksApi";
import { useIdentity } from "@/shell/identity";

import {
  deleteGoal,
  getGoal,
  updateGoal,
  type GoalDetail,
  type GoalEvent,
} from "./goalsApi";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; goal: GoalDetail }
  | { kind: "error"; message: string };

export function GoalDetailPage() {
  const params = useParams<{ goalId: string }>();
  const navigate = useNavigate();
  const goBack = useGoBack("/goals");
  const goalId = params.goalId ? Number(params.goalId) : NaN;
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  const reload = useCallback(async () => {
    if (Number.isNaN(goalId)) {
      setState({ kind: "error", message: "Invalid goal id" });
      return;
    }
    try {
      const goal = await getGoal(goalId);
      setState({ kind: "ready", goal });
    } catch (e) {
      setState({
        kind: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    }
  }, [goalId]);

  useEffect(() => {
    setState({ kind: "loading" });
    void reload();
  }, [reload]);

  const patchGoal = useCallback(
    async (patch: { is_done: boolean }) => {
      const next = await updateGoal(goalId, patch);
      setState({ kind: "ready", goal: next });
    },
    [goalId],
  );

  const removeGoal = useCallback(async () => {
    await deleteGoal(goalId);
    navigate("/goals", { replace: true });
  }, [goalId, navigate]);

  if (state.kind === "loading") {
    return (
      <div className="flex h-full items-center justify-center text-sm text-life-ink-3">
        Loading...
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
        <div className="text-sm text-red-500">
          Couldn't load goal: {state.message}
        </div>
        <button
          type="button"
          onClick={() => navigate("/goals")}
          className="text-xs text-life-ink-3 underline"
        >
          Back to goals
        </button>
      </div>
    );
  }

  return (
    <GoalDetailShell
      goal={state.goal}
      onBack={goBack}
      onPatch={patchGoal}
      onDelete={removeGoal}
      onReload={reload}
      onOpenTask={(taskId) => navigate(`/tasks/${taskId}`)}
    />
  );
}

function GoalDetailShell({
  goal,
  onBack,
  onPatch,
  onDelete,
  onReload,
  onOpenTask,
}: {
  goal: GoalDetail;
  onBack: () => void;
  onPatch: (patch: { is_done: boolean }) => Promise<void>;
  onDelete: () => Promise<void>;
  onReload: () => Promise<void>;
  onOpenTask: (taskId: number) => void;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col bg-life-bg">
      <GoalHeader
        goal={goal}
        onBack={onBack}
        onPatch={onPatch}
        onDelete={onDelete}
      />
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        <GoalOverview goal={goal} />
        <LinkedTasksSection goal={goal} onOpenTask={onOpenTask} onReload={onReload} />
        <GoalEventLog events={goal.events} />
      </div>
    </div>
  );
}

function GoalHeader({
  goal,
  onBack,
  onPatch,
  onDelete,
}: {
  goal: GoalDetail;
  onBack: () => void;
  onPatch: (patch: { is_done: boolean }) => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const [deleting, setDeleting] = useState(false);

  const toggleDone = async () => {
    await onPatch({ is_done: !goal.is_done });
  };

  const confirmAndDelete = async () => {
    const ok = window.confirm(
      `Delete "${goal.title}"? Linked tasks will stay, but their goal link and goal log will be removed. This cannot be undone.`,
    );
    if (!ok) return;
    setDeleting(true);
    try {
      await onDelete();
    } finally {
      setDeleting(false);
    }
  };

  return (
    <header className="border-b border-life-line bg-life-card px-4 pt-11 pb-3">
      <div className="mx-auto flex w-full max-w-(--goal-detail-max-width) flex-col gap-2"
        style={{ ["--goal-detail-max-width" as string]: "44rem" }}
      >
        <div className="flex items-center gap-1.5 text-xs text-life-ink-3">
          <button
            type="button"
            onClick={onBack}
            aria-label="Back to goals"
            className="-ml-1 inline-flex items-center gap-1 rounded px-1 py-0.5 hover:bg-life-bg"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Goals
          </button>
          <span className="ml-auto inline-flex items-center gap-1 rounded-full border border-life-line bg-life-bg px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.6px] text-life-ink-3">
            {goal.is_done ? (
              <CheckCircle2 className="h-3 w-3" />
            ) : (
              <Target className="h-3 w-3" />
            )}
            {goal.is_done ? "Done" : "Active"}
          </span>
        </div>

        <h1
          data-testid="goal-title"
          className={cn(
            "font-serif text-[26px] leading-tight",
            goal.is_done ? "text-life-ink-3 line-through" : "text-life-ink",
          )}
        >
          {goal.title}
        </h1>
        <div className="flex flex-wrap items-center gap-1.5">
          <Button
            type="button"
            size="sm"
            variant={goal.is_done ? "outline" : "default"}
            data-testid="goal-toggle-done"
            onClick={() => void toggleDone()}
            className="rounded-full"
          >
            {goal.is_done ? (
              <RotateCcw className="h-3.5 w-3.5" />
            ) : (
              <CheckCircle2 className="h-3.5 w-3.5" />
            )}
            {goal.is_done ? "Reopen" : "Complete"}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="destructive"
            data-testid="goal-delete"
            onClick={() => void confirmAndDelete()}
            disabled={deleting}
            className="rounded-full"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Delete
          </Button>
        </div>
      </div>
    </header>
  );
}

function GoalOverview({ goal }: { goal: GoalDetail }) {
  const description = goal.description?.trim();
  return (
    <section className="mb-5 flex flex-col gap-3">
      <div className="rounded-xl border border-life-line bg-life-card px-3 py-2.5">
        <h2 className="mb-1 text-[10px] font-bold uppercase tracking-[0.6px] text-life-ink-3">
          Details
        </h2>
        {description ? (
          <div className="text-[13px] leading-relaxed text-life-ink-2">
            <MarkdownView source={description} />
          </div>
        ) : (
          <p className="text-[13px] text-life-ink-3">
            No description yet.
          </p>
        )}
      </div>
    </section>
  );
}

function LinkedTasksSection({
  goal,
  onOpenTask,
  onReload,
}: {
  goal: GoalDetail;
  onOpenTask: (taskId: number) => void;
  onReload: () => Promise<void>;
}) {
  const { assistantName } = useIdentity();
  return (
    <section className="mb-5">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-[10px] font-bold uppercase tracking-[0.6px] text-life-ink-3">
          Linked tasks
        </h2>
        <span className="inline-flex items-center gap-1 text-[11px] text-life-ink-3">
          <ListTodo className="h-3 w-3" />
          {goal.tasks.length}
        </span>
      </div>
      <AddLinkedTaskForm
        goalId={goal.id}
        assistantName={assistantName}
        onCreated={onReload}
      />
      {goal.tasks.length > 0 ? (
        <div className="overflow-hidden rounded-xl border border-life-line bg-life-card">
          <div className="divide-y divide-life-line">
            {goal.tasks.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                onOpen={() => onOpenTask(task.id)}
                onChanged={() => void onReload()}
                assistantName={assistantName}
              />
            ))}
          </div>
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-life-line bg-life-card px-3 py-4 text-center text-[13px] text-life-ink-3">
          No linked tasks yet.
        </div>
      )}
    </section>
  );
}

function AddLinkedTaskForm({
  goalId,
  assistantName,
  onCreated,
}: {
  goalId: number;
  assistantName: string;
  onCreated: () => Promise<void>;
}) {
  const [title, setTitle] = useState("");
  const [assignee, setAssignee] = useState<Assignee>("user");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmedTitle = title.trim();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!trimmedTitle || submitting) return;
    try {
      setSubmitting(true);
      setError(null);
      await createTask({
        title: trimmedTitle,
        assignee,
        goal_id: goalId,
      });
      setTitle("");
      await onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={(event) => void submit(event)}
      className="mb-3 rounded-xl border border-life-line bg-life-card p-2.5"
    >
      <div className="flex items-center gap-2">
        <Input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Add a task to this goal"
          aria-label="Task title"
          className="min-w-0 flex-1 rounded-xl border-life-line bg-life-bg"
        />
        <Button
          type="submit"
          size="icon"
          aria-label="Add task"
          disabled={!trimmedTitle || submitting}
          className="h-10 w-10 shrink-0 rounded-full"
        >
          <Plus className="h-4 w-4" />
        </Button>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <span className="shrink-0 text-[11px] font-medium text-life-ink-3">
          Assign to
        </span>
        <div className="flex flex-wrap gap-1.5">
          <AssigneeChip
            active={assignee === "user"}
            label="Me"
            ariaLabel="Assign new task to me"
            onClick={() => setAssignee("user")}
          />
          <AssigneeChip
            active={assignee === "assistant"}
            label={assistantName}
            ariaLabel={`Assign new task to ${assistantName}`}
            onClick={() => setAssignee("assistant")}
          />
        </div>
      </div>
      {error ? (
        <p className="mt-2 text-[12px] text-red-500">
          Could not add task: {error}
        </p>
      ) : null}
    </form>
  );
}

function AssigneeChip({
  active,
  label,
  ariaLabel,
  onClick,
}: {
  active: boolean;
  label: string;
  ariaLabel: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "rounded-full border px-2.5 py-1 text-[11px] font-medium",
        active
          ? "border-life-accent bg-life-accent text-white"
          : "border-life-line bg-life-bg text-life-ink-2",
      )}
    >
      {label}
    </button>
  );
}

function GoalEventLog({ events }: { events: GoalEvent[] }) {
  return (
    <section className="pb-8">
      <h2 className="mb-2 text-[10px] font-bold uppercase tracking-[0.6px] text-life-ink-3">
        Goal log
      </h2>
      {events.length > 0 ? (
        <ol className="flex flex-col gap-2">
          {events.map((event) => (
            <GoalEventItem key={event.id} event={event} />
          ))}
        </ol>
      ) : (
        <div className="rounded-xl border border-dashed border-life-line bg-life-card px-3 py-4 text-center text-[13px] text-life-ink-3">
          No events yet.
        </div>
      )}
    </section>
  );
}

function GoalEventItem({ event }: { event: GoalEvent }) {
  return (
    <li className="rounded-xl border border-life-line bg-life-card px-3 py-2.5">
      <div className="mb-1 flex items-center gap-2 text-[11px] text-life-ink-3">
        <span className="inline-flex items-center gap-1 rounded-full bg-life-bg px-2 py-0.5 font-medium">
          <Circle className="h-2.5 w-2.5" />
          {eventKindLabel(event.kind)}
        </span>
        <span className="ml-auto">{formatDoAt(event.created_at)}</span>
      </div>
      {event.body ? (
        <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-life-ink-2">
          {event.body}
        </p>
      ) : null}
      {event.task_id && event.task_title ? (
        <Link
          to={`/tasks/${event.task_id}`}
          className="mt-1 inline-flex text-[12px] font-medium text-life-accent"
        >
          {event.task_title}
        </Link>
      ) : null}
    </li>
  );
}

function eventKindLabel(kind: string): string {
  switch (kind) {
    case "created":
      return "Created";
    case "updated":
      return "Updated";
    case "task_linked":
      return "Task linked";
    case "task_unlinked":
      return "Task unlinked";
    case "task_completed":
      return "Task completed";
    case "task_reopened":
      return "Task reopened";
    case "completed":
      return "Completed";
    case "reopened":
      return "Reopened";
    default:
      return "Note";
  }
}
