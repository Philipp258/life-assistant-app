import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useIdentity } from "@/shell/identity";

import { DescriptionEditor } from "./DescriptionEditor";

import {
  WHO_OPTIONS,
  whenOf,
  whenOptionsFor,
  whoOf,
  type When,
  type Who,
} from "./mode";
import {
  DoAtField,
  Field,
  IntervalRow,
  Pill,
  PillGroup,
} from "./taskFields";
import type { IntervalUnit, Task, TaskUpdate } from "./tasksApi";

export function EditTaskSheet({
  open,
  task,
  onClose,
  onPatch,
  onDelete,
}: {
  open: boolean;
  task: Task;
  onClose: () => void;
  onPatch: (patch: TaskUpdate) => Promise<void>;
  onDelete?: () => Promise<void>;
}) {
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
              Edit task
            </SheetTitle>
          </SheetHeader>

          <EditForm task={task} onPatch={onPatch} />

          <div className="mt-2 flex items-center justify-between gap-2 border-t border-life-line pt-4">
            {onDelete ? (
              <Button
                type="button"
                variant="destructive"
                size="sm"
                data-testid="task-delete"
                onClick={() => void confirmAndDelete(task, onDelete, onClose)}
                className="rounded-full"
              >
                Delete task
              </Button>
            ) : (
              <span />
            )}
            <Button
              type="button"
              size="sm"
              onClick={onClose}
              className="rounded-full"
            >
              Done
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

async function confirmAndDelete(
  task: Task,
  onDelete: () => Promise<void>,
  onClose: () => void,
) {
  const ok = window.confirm(
    `Delete "${task.title}"? This also removes its chat history and cannot be undone.`,
  );
  if (!ok) return;
  await onDelete();
  onClose();
}

function EditForm({
  task,
  onPatch,
}: {
  task: Task;
  onPatch: (patch: TaskUpdate) => Promise<void>;
}) {
  const { assistantName } = useIdentity();
  const [titleDraft, setTitleDraft] = useState(task.title);
  const [descEditorOpen, setDescEditorOpen] = useState(false);

  useEffect(() => setTitleDraft(task.title), [task.title]);

  const commitTitle = async () => {
    const v = titleDraft.trim();
    if (!v || v === task.title) {
      setTitleDraft(task.title);
      return;
    }
    await onPatch({ title: v });
  };

  const descPreview = (task.description ?? "").trim();

  const setWho = async (next: Who) => {
    await onPatch({ assignee: next === "me" ? "user" : "assistant" });
  };

  const setWhen = async (next: When) => {
    const assignee = task.assignee;
    switch (next) {
      case "now":
        await onPatch({
          assignee,
          do_at: null,
          interval_unit: null,
          interval_count: null,
        });
        return;
      case "later":
        await onPatch({
          assignee,
          do_at:
            task.do_at ??
            new Date(Date.now() + 60 * 60 * 1000).toISOString(),
          interval_unit: null,
          interval_count: null,
        });
        return;
      case "regularly":
        await onPatch({
          assignee,
          interval_unit: task.interval_unit ?? "week",
          interval_count: task.interval_count ?? 1,
        });
        return;
    }
  };

  const handleDoAtChange = async (v: string) => {
    if (!v) {
      await onPatch({ do_at: null });
      return;
    }
    await onPatch({ do_at: new Date(v).toISOString() });
  };

  const handleDueAtChange = async (v: string) => {
    if (!v) {
      await onPatch({ due_at: null });
      return;
    }
    await onPatch({ due_at: new Date(v).toISOString() });
  };

  const handleIntervalChange = async (unit: IntervalUnit, count: number) => {
    if (!Number.isFinite(count) || count < 1) return;
    await onPatch({ interval_unit: unit, interval_count: Math.floor(count) });
  };

  const toggleDone = async () => {
    await onPatch({ is_done: !task.is_done });
  };

  const who = whoOf(task);
  const when = whenOf(task);
  const whenOptions = whenOptionsFor(who);

  return (
    <div className="flex flex-col gap-4">
      <Field label="Title" htmlFor="edit-task-title">
        <Input
          id="edit-task-title"
          value={titleDraft}
          onChange={(e) => setTitleDraft(e.target.value)}
          onBlur={commitTitle}
          className="rounded-xl border-life-line bg-life-card"
        />
      </Field>

      <Field label="Description">
        <button
          type="button"
          data-testid="edit-task-description-open"
          onClick={() => setDescEditorOpen(true)}
          className="w-full truncate rounded-xl border border-life-line bg-life-card px-3 py-2.5 text-left text-[13px] text-life-ink-2 hover:border-life-accent/40"
        >
          {descPreview ? (
            <span className="line-clamp-2 whitespace-pre-wrap">
              {descPreview}
            </span>
          ) : (
            <span className="text-life-ink-3">Add a description…</span>
          )}
        </button>
      </Field>

      <PillGroup label="Assignee">
        {WHO_OPTIONS.map((o) => (
          <Pill
            key={o.v}
            label={o.v === "assistant" ? assistantName : o.label}
            on={o.v === who}
            onClick={() => void setWho(o.v)}
          />
        ))}
      </PillGroup>

      <PillGroup label="When?">
        {whenOptions.map((o) => (
          <Pill
            key={o.v}
            label={o.label}
            on={o.v === when}
            onClick={() => void setWhen(o.v)}
            title={o.hint}
          />
        ))}
      </PillGroup>

      {when === "later" && (
        <DoAtField
          id="edit-task-do-at"
          label="Start at"
          value={task.do_at}
          onChange={handleDoAtChange}
        />
      )}

      {when === "regularly" && (
        <div className="flex flex-col gap-2">
          <IntervalRow
            unit={task.interval_unit ?? "week"}
            count={task.interval_count ?? 1}
            onChange={handleIntervalChange}
          />
          <DoAtField
            id="edit-task-do-at"
            label={who === "me" ? "Optional first run at" : "Next run at"}
            value={task.do_at}
            onChange={handleDoAtChange}
          />
        </div>
      )}

      <DoAtField
        id="edit-task-due-at"
        label="Due by"
        value={task.due_at}
        onChange={handleDueAtChange}
      />

      <PillGroup label="Status">
        <Pill
          label={task.is_done ? "Done" : "Not done"}
          on={task.is_done}
          onClick={() => void toggleDone()}
        />
      </PillGroup>

      <DescriptionEditor
        open={descEditorOpen}
        initialValue={task.description ?? ""}
        onSave={(v) => onPatch({ description: v })}
        onClose={() => setDescEditorOpen(false)}
      />
    </div>
  );
}
