import type { IntervalUnit, TaskKind } from "./tasksApi";

export const KIND_LABEL: Record<TaskKind, string> = {
  routine: "Routine",
  "scheduled-job": "Scheduled",
  job: "Job",
  deadline: "Deadline",
  "scheduled-todo": "Scheduled todo",
  todo: "Todo",
};

const UNIT_LABEL: Record<IntervalUnit, { one: string; many: string }> = {
  hour: { one: "Hourly", many: "hours" },
  day: { one: "Daily", many: "days" },
  week: { one: "Weekly", many: "weeks" },
};

export function formatInterval(
  unit: IntervalUnit,
  count: number,
): string {
  if (count <= 1) return UNIT_LABEL[unit].one;
  return `Every ${count} ${UNIT_LABEL[unit].many}`;
}

export function formatDoAt(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  const time = d.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  if (sameDay) return `Today ${time}`;
  const date = d.toLocaleDateString([], { month: "short", day: "numeric" });
  return `${date} · ${time}`;
}

/**
 * Compact "when was this completed" string. Recent completions are shown
 * as a relative phrase ("Just now", "5m ago", "2h ago") so an accidental
 * checkoff is easy to recognise; older ones fall back to a date stamp.
 */
export function formatCompletedAt(
  iso: string,
  now: Date = new Date(),
): string {
  const d = new Date(iso);
  const diffMs = now.getTime() - d.getTime();
  if (!Number.isFinite(diffMs)) return "";
  const diffMin = Math.round(diffMs / 60_000);
  if (diffMin < 1) return "Just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const sameYear = d.getFullYear() === now.getFullYear();
  return d.toLocaleDateString([], {
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
  });
}

/**
 * "Was this task completed within the last 24 hours?" — used to auto-open
 * the Done section so an accidental check-off is one click away.
 */
export function wasRecentlyCompleted(
  iso: string | null,
  now: Date = new Date(),
): boolean {
  if (!iso) return false;
  const d = new Date(iso);
  const diffMs = now.getTime() - d.getTime();
  return diffMs >= 0 && diffMs < 24 * 60 * 60 * 1000;
}
