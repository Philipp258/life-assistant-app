import type { Task } from "./tasksApi";

/** Normalise a query/haystack the same way: lowercase + collapsed whitespace. */
function normalise(s: string): string {
  return s.toLowerCase().replace(/\s+/g, " ").trim();
}

/** Split the query into AND-joined terms so "tax april" matches a task that
 * has both words anywhere in its searchable text. Empty tokens are dropped. */
export function tokenize(query: string): string[] {
  return normalise(query).split(" ").filter(Boolean);
}

/** Build the searchable haystack for a task. Title carries most signal, but
 * we also include description so a search like "groceries" still finds a
 * task that mentions it only there. */
function haystack(task: Task): string {
  const parts: string[] = [task.title];
  if (task.description) parts.push(task.description);
  return normalise(parts.join(" "));
}

export function matchesTaskSearch(task: Task, query: string): boolean {
  const tokens = tokenize(query);
  if (tokens.length === 0) return true;
  const hay = haystack(task);
  return tokens.every((t) => hay.includes(t));
}

export function filterTasksBySearch(tasks: Task[], query: string): Task[] {
  if (tokenize(query).length === 0) return tasks;
  return tasks.filter((t) => matchesTaskSearch(t, query));
}
