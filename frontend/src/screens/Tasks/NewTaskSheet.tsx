import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { useIdentity } from "@/shell/identity";

import { listGoals, type Goal } from "@/screens/Goals/goalsApi";

import { WHO_OPTIONS, whenOptionsFor, type When, type Who } from "./mode";
import { Field, IntervalRow, Pill, PillGroup } from "./taskFields";
import type { IntervalUnit, TaskCreate } from "./tasksApi";

type NewTaskSheetProps = {
  open: boolean;
  onClose: () => void;
  onCreate: (data: TaskCreate) => void | Promise<void>;
};

export function NewTaskSheet({
  open,
  onClose,
  onCreate,
}: NewTaskSheetProps) {
  const { assistantName } = useIdentity();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [who, setWho] = useState<Who>("me");
  const [when, setWhen] = useState<When>("now");
  const [doAt, setDoAt] = useState("");
  const [dueAt, setDueAt] = useState("");
  const [unit, setUnit] = useState<IntervalUnit>("week");
  const [count, setCount] = useState(1);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [selectedGoalId, setSelectedGoalId] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    listGoals(false)
      .then(setGoals)
      .catch(() => undefined);
  }, [open]);

  // "Me" doesn't surface a "Later" option (passive dated rows with no
  // firing aren't useful) — snap the When pill back to a valid choice
  // when the user flips Who.
  const whenOptions = useMemo(() => whenOptionsFor(who), [who]);
  useEffect(() => {
    if (!whenOptions.some((o) => o.v === when)) setWhen(whenOptions[0].v);
  }, [whenOptions, when]);

  const reset = () => {
    setTitle("");
    setDescription("");
    setWho("me");
    setWhen("now");
    setDoAt("");
    setDueAt("");
    setUnit("week");
    setCount(1);
    setSelectedGoalId(null);
  };

  const handleClose = () => {
    if (submitting) return;
    reset();
    onClose();
  };

  const needsDoAt = when === "later";
  const needsInterval = when === "regularly";

  async function submit() {
    if (!title.trim()) return;
    const payload: TaskCreate = {
      title: title.trim(),
      description: description.trim() || null,
      assignee: who === "me" ? "user" : "assistant",
    };
    if (selectedGoalId !== null) payload.goal_id = selectedGoalId;
    if (dueAt) payload.due_at = new Date(dueAt).toISOString();
    if (needsDoAt) {
      if (!doAt) return;
      payload.do_at = new Date(doAt).toISOString();
    }
    if (needsInterval) {
      if (!Number.isFinite(count) || count < 1) return;
      payload.interval_unit = unit;
      payload.interval_count = Math.floor(count);
      if (doAt) payload.do_at = new Date(doAt).toISOString();
    }
    try {
      setSubmitting(true);
      await onCreate(payload);
      reset();
      onClose();
    } finally {
      setSubmitting(false);
    }
  }

  const submitDisabled =
    !title.trim()
    || submitting
    || (needsDoAt && !doAt)
    || (needsInterval && (!Number.isFinite(count) || count < 1));

  return (
    <Sheet open={open} onOpenChange={(o) => !o && handleClose()}>
      <SheetContent
        side="bottom"
        className="h-auto max-h-[90dvh] overflow-y-auto rounded-t-3xl border-life-line bg-life-bg p-0 text-life-ink sm:max-w-none"
        showCloseButton={false}
      >
        <div className="flex flex-col gap-4 px-5 pt-3 pb-10">
          <div className="mx-auto my-1 h-1 w-10 rounded bg-life-line" />
          <SheetHeader className="gap-1 p-0 text-left">
            <SheetDescription className="text-[10px] font-bold tracking-[0.6px] text-life-accent uppercase">
              New task
            </SheetDescription>
            <SheetTitle className="font-serif text-[28px] leading-[1.1] font-normal text-life-ink">
              What needs doing?
            </SheetTitle>
          </SheetHeader>

          <div className="flex flex-col gap-4">
            <Field label="Title" htmlFor="task-title">
              <Input
                id="task-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Buy milk"
                autoFocus
                className="rounded-xl border-life-line bg-life-card"
              />
            </Field>

            <Field
              label="Description"
              htmlFor="task-desc"
              hint="Markdown is supported: headings, links, lists, checkboxes, code, and tables."
            >
              <Textarea
                id="task-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Optional extra context"
                rows={3}
                className="rounded-xl border-life-line bg-life-card"
              />
            </Field>

            {goals.length > 0 && (
              <Field label="Goal" htmlFor="task-goal">
                <select
                  id="task-goal"
                  value={selectedGoalId === null ? "" : String(selectedGoalId)}
                  onChange={(event) => {
                    const value = event.target.value;
                    setSelectedGoalId(value ? Number(value) : null);
                  }}
                  className="h-10 w-full rounded-xl border border-life-line bg-life-card px-3 text-sm text-life-ink outline-none focus:border-life-accent focus:ring-2 focus:ring-life-accent/20"
                >
                  <option value="">No goal</option>
                  {goals.map((goal) => (
                    <option key={goal.id} value={goal.id}>
                      {goal.title}
                    </option>
                  ))}
                </select>
              </Field>
            )}

            <PillGroup label="Assignee">
              {WHO_OPTIONS.map((o) => (
                <Pill
                  key={o.v}
                  label={o.v === "assistant" ? assistantName : o.label}
                  on={o.v === who}
                  onClick={() => setWho(o.v)}
                />
              ))}
            </PillGroup>

            <PillGroup label="When?">
              {whenOptions.map((o) => (
                <Pill
                  key={o.v}
                  label={o.label}
                  on={o.v === when}
                  onClick={() => setWhen(o.v)}
                  title={o.hint}
                />
              ))}
            </PillGroup>

            {needsDoAt && (
              <Field
                label={who === "assistant" ? "Run at" : "Remind me at"}
                htmlFor="task-do-at"
              >
                <Input
                  id="task-do-at"
                  type="datetime-local"
                  value={doAt}
                  onChange={(e) => setDoAt(e.target.value)}
                  className="rounded-xl border-life-line bg-life-card"
                />
              </Field>
            )}

            {needsInterval && (
              <div className="flex flex-col gap-2">
                <IntervalRow
                  unit={unit}
                  count={count}
                  onChange={(u, c) => {
                    setUnit(u);
                    setCount(c);
                  }}
                />
                <Field
                  label={who === "me" ? "Optional first run at" : "Next run at"}
                  htmlFor="task-routine-first"
                >
                  <Input
                    id="task-routine-first"
                    type="datetime-local"
                    value={doAt}
                    onChange={(e) => setDoAt(e.target.value)}
                    className="rounded-xl border-life-line bg-life-card"
                  />
                </Field>
              </div>
            )}

            <Field label="Due by (optional)" htmlFor="task-due-at">
              <Input
                id="task-due-at"
                type="datetime-local"
                value={dueAt}
                onChange={(e) => setDueAt(e.target.value)}
                className="rounded-xl border-life-line bg-life-card"
              />
            </Field>
          </div>

          <div className="flex gap-2">
            <Button
              type="button"
              className="flex-1 rounded-full bg-life-accent text-white hover:bg-life-accent"
              disabled={submitDisabled}
              onClick={submit}
            >
              {submitting ? "Saving…" : "Save"}
            </Button>
            <Button
              type="button"
              variant="outline"
              className="rounded-full border-life-line text-life-ink-2"
              onClick={handleClose}
              disabled={submitting}
            >
              Cancel
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
