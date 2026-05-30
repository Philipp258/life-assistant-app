import type { Task } from "./tasksApi";

export type Who = "me" | "assistant";
export type When = "now" | "later" | "regularly";

export const WHO_OPTIONS: { v: Who; label: string }[] = [
  { v: "me", label: "Me" },
  { v: "assistant", label: "Assistant" },
];

export const WHEN_OPTIONS: { v: When; label: string; hint: string }[] = [
  { v: "now", label: "Now", hint: "Starts immediately." },
  { v: "later", label: "Later", hint: "Starts at the time you pick." },
  {
    v: "regularly",
    label: "Regularly",
    hint: "Repeats on the cadence you set.",
  },
];

/** When options offered for a given Who. Me skips "Later" — passive
 * passive dated rows with no firing aren't useful; recurring chores are. */
export function whenOptionsFor(who: Who): typeof WHEN_OPTIONS {
  if (who === "me") return WHEN_OPTIONS.filter((o) => o.v !== "later");
  return WHEN_OPTIONS;
}

export function whoOf(task: Pick<Task, "assignee">): Who {
  return task.assignee === "user" ? "me" : "assistant";
}

export function whenOf(
  task: Pick<Task, "do_at" | "interval_unit">,
): When {
  if (task.interval_unit) return "regularly";
  if (task.do_at) return "later";
  return "now";
}
