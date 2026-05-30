import { apiFetch, jsonOrThrow } from "@/lib/api";
import type { Task } from "@/screens/Tasks/tasksApi";

export type Goal = {
  id: number;
  title: string;
  description: string | null;
  is_done: boolean;
  open_tasks_count: number;
  done_tasks_count: number;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type GoalEvent = {
  id: number;
  goal_id: number;
  task_id: number | null;
  task_title: string | null;
  kind: string;
  body: string | null;
  created_at: string;
};

export type GoalDetail = Goal & {
  tasks: Task[];
  events: GoalEvent[];
};

export type GoalCreate = {
  title: string;
  description?: string | null;
  task_ids?: number[];
};

export type GoalUpdate = Partial<{
  title: string;
  description: string | null;
  is_done: boolean;
}>;

export async function listGoals(done?: boolean): Promise<Goal[]> {
  const qs = new URLSearchParams();
  if (done !== undefined) qs.set("done", String(done));
  const url = qs.toString() ? `/api/goals?${qs}` : "/api/goals";
  const r = await apiFetch(url);
  const body = await jsonOrThrow<{ goals: Goal[] }>(r);
  return body.goals;
}

export async function getGoal(id: number): Promise<GoalDetail> {
  const r = await apiFetch(`/api/goals/${id}`);
  return jsonOrThrow<GoalDetail>(r);
}

export async function createGoal(data: GoalCreate): Promise<Goal> {
  const r = await apiFetch("/api/goals", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(data),
  });
  return jsonOrThrow<Goal>(r);
}

export async function updateGoal(
  id: number,
  patch: GoalUpdate,
): Promise<GoalDetail> {
  const r = await apiFetch(`/api/goals/${id}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(patch),
  });
  return jsonOrThrow<GoalDetail>(r);
}

export async function deleteGoal(id: number): Promise<void> {
  const r = await apiFetch(`/api/goals/${id}`, { method: "DELETE" });
  if (!r.ok) {
    const body = await r.text().catch(() => "");
    throw new Error(`${r.status} ${r.statusText}: ${body}`);
  }
}
