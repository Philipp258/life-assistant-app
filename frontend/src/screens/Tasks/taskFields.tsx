import { useEffect, useState } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

import { formatDoAt } from "./format";
import type { IntervalUnit } from "./tasksApi";

/** A labelled column wrapper used by both the new- and edit-task sheets so
 * field spacing and typography stay in lock-step. */
export function Field({
  label,
  htmlFor,
  children,
  hint,
}: {
  label: string;
  htmlFor?: string;
  hint?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={htmlFor} className="text-life-ink-2">
        {label}
      </Label>
      {children}
      {hint ? <p className="text-[11px] text-life-ink-3">{hint}</p> : null}
    </div>
  );
}

/** A small caption + pill row. The caption uses the same uppercase
 * micro-label as the rest of the task UI ("ASSIGNEE", "WHEN", …). */
export function PillGroup({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[10px] font-bold uppercase tracking-[0.6px] text-life-ink-3">
        {label}
      </span>
      <div className="flex flex-wrap gap-1.5">{children}</div>
    </div>
  );
}

export function Pill({
  label,
  on,
  onClick,
  title,
}: {
  label: string;
  on: boolean;
  onClick: () => void;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      title={title}
      className={cn(
        "rounded-full border px-3 py-1.5 text-[12px] font-medium transition-colors",
        on
          ? "border-life-accent bg-life-accent text-white"
          : "border-life-line bg-life-card text-life-ink-2 hover:bg-life-bg",
      )}
    >
      {label}
    </button>
  );
}

function toLocalDatetimeValue(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

/** A datetime-local input + human summary + clear button. Used for
 * do_at and due_at in both sheets. `value` is an ISO string or null;
 * `onChange` receives the raw datetime-local string (or "" for clear). */
export function DoAtField({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string | null;
  onChange: (v: string) => void | Promise<void>;
}) {
  const local = toLocalDatetimeValue(value);
  const summary = value ? formatDoAt(value) : "not set";
  return (
    <Field label={label} htmlFor={id}>
      <div className="flex items-center gap-2">
        <Input
          id={id}
          type="datetime-local"
          value={local}
          onChange={(e) => void onChange(e.target.value)}
          className="rounded-xl border-life-line bg-life-card"
        />
        <span className="shrink-0 text-[12px] text-life-ink-3">{summary}</span>
        {value && (
          <button
            type="button"
            onClick={() => void onChange("")}
            aria-label={`Clear ${label.toLowerCase()}`}
            className="rounded-full px-2 py-0.5 text-[12px] text-life-ink-3 hover:bg-life-card"
          >
            clear
          </button>
        )}
      </div>
    </Field>
  );
}

/** "Every <count> <unit>" row, used by both sheets when the user picks
 * a recurring task. Count is buffered in local state so an in-progress
 * edit doesn't blow up on every keystroke. */
export function IntervalRow({
  unit,
  count,
  onChange,
}: {
  unit: IntervalUnit;
  count: number;
  onChange: (unit: IntervalUnit, count: number) => void | Promise<void>;
}) {
  const [draftCount, setDraftCount] = useState(String(count));
  useEffect(() => {
    setDraftCount(String(count));
  }, [count]);

  const commitCount = () => {
    const n = Number(draftCount);
    if (!Number.isFinite(n) || n < 1) {
      setDraftCount(String(count));
      return;
    }
    if (Math.floor(n) === count) return;
    void onChange(unit, Math.floor(n));
  };

  return (
    <Field label="Every">
      <div className="flex items-center gap-2">
        <Input
          type="number"
          min={1}
          value={draftCount}
          onChange={(e) => setDraftCount(e.target.value)}
          onBlur={commitCount}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          }}
          aria-label="Interval count"
          className="w-20 rounded-xl border-life-line bg-life-card"
        />
        <Select
          value={unit}
          onValueChange={(v) => void onChange(v as IntervalUnit, count)}
        >
          <SelectTrigger className="w-[140px] rounded-xl border-life-line bg-life-card">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="hour">Hours</SelectItem>
            <SelectItem value="day">Days</SelectItem>
            <SelectItem value="week">Weeks</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </Field>
  );
}
