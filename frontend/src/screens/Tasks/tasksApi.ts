import { apiFetch, jsonOrThrow } from "@/lib/api";

export type IntervalUnit = "hour" | "day" | "week";
export type TaskState = "running" | "up_next" | "yours" | "done";
export type Assignee = "user" | "assistant";
export type TaskKind =
  | "routine"
  | "scheduled-job"
  | "job"
  | "deadline"
  | "scheduled-todo"
  | "todo";

export type Task = {
  id: number;
  title: string;
  description: string | null;
  is_done: boolean;
  assignee: Assignee;
  chat_session_id: number;
  goal_id: number | null;
  goal_title: string | null;
  do_at: string | null;
  due_at: string | null;
  interval_unit: IntervalUnit | null;
  interval_count: number | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  state: TaskState;
  kind: TaskKind;
  source_chat_session_id?: number | null;
  source_chat_title?: string | null;
};

export type TaskCreate = {
  title: string;
  description?: string | null;
  assignee?: Assignee;
  do_at?: string | null;
  due_at?: string | null;
  interval_unit?: IntervalUnit | null;
  interval_count?: number | null;
  goal_id?: number | null;
};

export type TaskUpdate = Partial<{
  title: string;
  description: string | null;
  is_done: boolean;
  assignee: Assignee;
  do_at: string | null;
  due_at: string | null;
  interval_unit: IntervalUnit | null;
  interval_count: number | null;
  goal_id: number | null;
}>;

export type ListTasksParams = {
  assignee?: "user" | "assistant" | null;
  statuses?: ("open" | "scheduled" | "waiting" | "done")[];
  due?: "today" | "week" | null;
  // Lifecycle slice: omit = legacy (open+done), false = open feed
  // (last-activity order), true = done tail (use listDoneTasks instead).
  done?: boolean;
};

function buildTaskQuery(params: ListTasksParams): URLSearchParams {
  const qs = new URLSearchParams();
  params.statuses?.forEach((s) => qs.append("status", s));
  if (params.assignee) qs.append("assignee", params.assignee);
  if (params.due) qs.append("due", params.due);
  if (params.done !== undefined) qs.set("done", String(params.done));
  return qs;
}

export async function listTasks(
  params: ListTasksParams = {},
): Promise<Task[]> {
  const qs = buildTaskQuery(params);
  const url = qs.toString() ? `/api/tasks?${qs}` : "/api/tasks";
  const r = await apiFetch(url);
  const body = await jsonOrThrow<{ tasks: Task[] }>(r);
  return body.tasks;
}

export type DonePage = { tasks: Task[]; nextCursor: string | null };

/**
 * One keyset page of the done archive (`completed_at desc`). Pass the
 * previous page's `nextCursor` to walk forward; `nextCursor: null` means
 * the archive is exhausted. Only the done tail paginates — the open feed
 * is bounded and fetched whole via `listTasks({ done: false })`.
 */
export async function listDoneTasks(
  params: Omit<ListTasksParams, "done" | "statuses"> = {},
  cursor?: string | null,
  limit = 50,
): Promise<DonePage> {
  const qs = buildTaskQuery({ ...params, done: true });
  qs.set("limit", String(limit));
  if (cursor) qs.set("cursor", cursor);
  const r = await apiFetch(`/api/tasks?${qs}`);
  const body = await jsonOrThrow<{ tasks: Task[]; next_cursor: string | null }>(
    r,
  );
  return { tasks: body.tasks, nextCursor: body.next_cursor ?? null };
}

export async function getTask(id: number): Promise<Task> {
  const r = await apiFetch(`/api/tasks/${id}`);
  return jsonOrThrow<Task>(r);
}

export async function createTask(data: TaskCreate): Promise<Task> {
  const r = await apiFetch("/api/tasks", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(data),
  });
  return jsonOrThrow<Task>(r);
}

export async function updateTask(
  id: number,
  patch: TaskUpdate,
): Promise<Task> {
  const r = await apiFetch(`/api/tasks/${id}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(patch),
  });
  return jsonOrThrow<Task>(r);
}

export async function deleteTask(id: number): Promise<void> {
  const r = await apiFetch(`/api/tasks/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
}

export async function runTaskNow(id: number): Promise<Task> {
  const r = await apiFetch(`/api/tasks/${id}/run-now`, { method: "POST" });
  return jsonOrThrow<Task>(r);
}

export type TaskActivity = {
  active_session_ids: number[];
  stalled_session_ids: number[];
  errored_session_ids: number[];
};

export async function fetchTaskActivity(): Promise<TaskActivity> {
  const r = await apiFetch("/api/tasks/activity");
  return jsonOrThrow<TaskActivity>(r);
}
