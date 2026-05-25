export type FilterBlob = {
  labels?: string[];
  assignee?: "user" | "assistant" | null;
  statuses?: ("open" | "scheduled" | "waiting" | "done")[];
  due?: "today" | "week" | null;
};

export type GroupBy = "none";

export type SavedTaskView = {
  id: number;
  name: string;
  icon: string | null;
  filters: FilterBlob;
  group_by: GroupBy;
  sort_index: number;
  is_default: boolean;
};

export type SavedTaskViewCreate = {
  name: string;
  icon?: string | null;
  filters: FilterBlob;
  group_by: GroupBy;
};

export type SavedTaskViewUpdate = Partial<SavedTaskViewCreate> & {
  is_default?: boolean;
  sort_index?: number;
};

export async function listViews(): Promise<SavedTaskView[]> {
  const res = await fetch("/api/saved-task-views", { credentials: "include" });
  if (!res.ok) throw new Error(`listViews ${res.status}`);
  return (await res.json()).views;
}

export async function createView(body: SavedTaskViewCreate): Promise<SavedTaskView> {
  const res = await fetch("/api/saved-task-views", {
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`createView ${res.status}`);
  return res.json();
}

export async function updateView(id: number, body: SavedTaskViewUpdate): Promise<SavedTaskView> {
  const res = await fetch(`/api/saved-task-views/${id}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`updateView ${res.status}`);
  return res.json();
}

export async function reorderViews(orderedIds: number[]): Promise<SavedTaskView[]> {
  // Issue parallel PATCHes so the round-trip stays fast. The server stores
  // sort_index as a plain integer, so concurrent updates can't conflict on
  // disjoint rows.
  const updated = await Promise.all(
    orderedIds.map((id, idx) => updateView(id, { sort_index: idx })),
  );
  return updated;
}

export async function deleteView(id: number): Promise<void> {
  const res = await fetch(`/api/saved-task-views/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!res.ok) throw new Error(`deleteView ${res.status}`);
}
