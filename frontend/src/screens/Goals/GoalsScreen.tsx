import { CheckCircle2, Circle, ListTodo, Plus, Target } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { Header } from "@/shell/Header";

import { createGoal, listGoals, type Goal, type GoalCreate } from "./goalsApi";

type GoalMode = "active" | "done";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; goals: Goal[] }
  | { kind: "error"; message: string };

export function GoalsScreen() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<GoalMode>("active");
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [composerOpen, setComposerOpen] = useState(false);

  const reload = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      const goals = await listGoals(mode === "done");
      setState({ kind: "ready", goals });
    } catch (e) {
      setState({
        kind: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    }
  }, [mode]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const activeCount = useMemo(() => {
    if (state.kind !== "ready") return null;
    return state.goals.filter((goal) => !goal.is_done).length;
  }, [state]);

  const handleCreate = async (data: GoalCreate) => {
    const created = await createGoal(data);
    setComposerOpen(false);
    navigate(`/goals/${created.id}`);
  };

  return (
    <div className="flex h-full flex-col">
      <Header
        title="Goals"
        subtitle={
          activeCount === null
            ? "OUTCOMES"
            : `${activeCount} ACTIVE OUTCOME${activeCount === 1 ? "" : "S"}`
        }
        right={
          <button
            type="button"
            onClick={() => setComposerOpen(true)}
            className="flex items-center gap-1.5 rounded-full bg-life-accent px-3.5 py-2 text-[13px] font-medium text-white"
          >
            <Plus className="h-4 w-4" />
            New
          </button>
        }
      />

      <div className="flex gap-2 border-b border-life-line px-5 pb-3">
        <GoalModeButton
          label="Active"
          active={mode === "active"}
          onClick={() => setMode("active")}
        />
        <GoalModeButton
          label="Done"
          active={mode === "done"}
          onClick={() => setMode("done")}
        />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {state.kind === "loading" ? (
          <div className="py-10 text-center text-sm text-life-ink-3">
            Loading...
          </div>
        ) : state.kind === "error" ? (
          <div className="py-10 text-center text-sm text-red-500">
            Couldn't load goals: {state.message}
          </div>
        ) : state.goals.length > 0 ? (
          <div className="flex flex-col gap-2.5">
            {state.goals.map((goal) => (
              <GoalListCard
                key={goal.id}
                goal={goal}
                onOpen={() => navigate(`/goals/${goal.id}`)}
              />
            ))}
          </div>
        ) : (
          <EmptyGoals mode={mode} onCreate={() => setComposerOpen(true)} />
        )}
      </div>

      <NewGoalSheet
        open={composerOpen}
        onClose={() => setComposerOpen(false)}
        onCreate={handleCreate}
      />
    </div>
  );
}

function GoalModeButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full border px-3 py-1.5 text-[12px] font-medium",
        active
          ? "border-life-accent bg-life-accent text-white"
          : "border-life-line bg-life-card text-life-ink-2",
      )}
    >
      {label}
    </button>
  );
}

function GoalListCard({ goal, onOpen }: { goal: Goal; onOpen: () => void }) {
  const totalTasks = goal.open_tasks_count + goal.done_tasks_count;
  return (
    <button
      type="button"
      onClick={onOpen}
      data-testid="goal-card"
      className="w-full rounded-xl border border-life-line bg-life-card px-3.5 py-3 text-left transition-colors hover:border-life-accent/40"
    >
      <div className="mb-2 flex items-start gap-2">
        <span
          className={cn(
            "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full",
            goal.is_done
              ? "bg-life-done text-white"
              : "bg-life-accent-soft text-life-accent",
          )}
        >
          {goal.is_done ? (
            <CheckCircle2 className="h-3.5 w-3.5" />
          ) : (
            <Target className="h-3.5 w-3.5" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div
            className={cn(
              "line-clamp-2 break-words text-[15px] font-semibold leading-snug",
              goal.is_done ? "text-life-ink-3 line-through" : "text-life-ink",
            )}
          >
            {goal.title}
          </div>
          {goal.description ? (
            <div className="mt-1 line-clamp-2 text-[12.5px] leading-relaxed text-life-ink-3">
              {goal.description}
            </div>
          ) : null}
        </div>
      </div>
      <div className="flex items-center gap-2 text-[11.5px] text-life-ink-3">
        <span className="inline-flex items-center gap-1">
          <ListTodo className="h-3 w-3" />
          {goal.open_tasks_count} open
          {totalTasks > 0 ? ` / ${goal.done_tasks_count} done` : ""}
        </span>
        <span className="ml-auto">{formatGoalDate(goal.updated_at)}</span>
      </div>
    </button>
  );
}

function EmptyGoals({
  mode,
  onCreate,
}: {
  mode: GoalMode;
  onCreate: () => void;
}) {
  return (
    <div className="flex flex-col items-center gap-3 py-12 text-center">
      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-life-card text-life-ink-3 ring-1 ring-life-line">
        {mode === "done" ? (
          <CheckCircle2 className="h-5 w-5" />
        ) : (
          <Target className="h-5 w-5" />
        )}
      </div>
      <div className="max-w-[260px] text-sm text-life-ink-3">
        {mode === "done" ? "No completed goals yet." : "No active goals yet."}
      </div>
      {mode === "active" ? (
        <Button type="button" size="sm" onClick={onCreate} className="rounded-full">
          <Plus className="h-3.5 w-3.5" />
          New goal
        </Button>
      ) : null}
    </div>
  );
}

function NewGoalSheet({
  open,
  onClose,
  onCreate,
}: {
  open: boolean;
  onClose: () => void;
  onCreate: (data: GoalCreate) => Promise<void>;
}) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setTitle("");
    setDescription("");
    setSaving(false);
  }, [open]);

  const submit = async () => {
    const cleanTitle = title.trim();
    if (!cleanTitle || saving) return;
    setSaving(true);
    try {
      await onCreate({
        title: cleanTitle,
        description: description.trim() || null,
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent
        side="bottom"
        className="h-auto max-h-[90dvh] overflow-y-auto rounded-t-3xl border-life-line bg-life-bg p-0 text-life-ink sm:max-w-none"
        showCloseButton={false}
      >
        <div className="flex flex-col gap-4 px-5 pt-3 pb-10">
          <div className="mx-auto my-1 h-1 w-10 rounded bg-life-line" />
          <SheetHeader className="gap-1 p-0 text-left">
            <SheetTitle className="font-serif text-[22px] leading-tight font-normal text-life-ink">
              New goal
            </SheetTitle>
          </SheetHeader>
          <label className="flex flex-col gap-1.5 text-[12px] font-semibold uppercase tracking-[0.5px] text-life-ink-3">
            Title
            <Input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="e.g. Get more fit"
              className="rounded-xl border-life-line bg-life-card text-[15px] normal-case tracking-normal text-life-ink"
            />
          </label>
          <label className="flex flex-col gap-1.5 text-[12px] font-semibold uppercase tracking-[0.5px] text-life-ink-3">
            Notes
            <Textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="Optional context"
              className="min-h-[108px] rounded-xl border-life-line bg-life-card text-[14px] normal-case tracking-normal text-life-ink"
            />
          </label>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={onClose}
              className="rounded-full"
            >
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => void submit()}
              disabled={!title.trim() || saving}
              className="rounded-full"
            >
              <Circle className="h-3.5 w-3.5" />
              Create
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function formatGoalDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(date);
}
