export type Label = {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  color: string | null;
  icon: string | null;
};

export type LabelCreate = {
  slug: string;
  name: string;
  description?: string | null;
  color?: string | null;
  icon?: string | null;
};

export type LabelUpdate = Partial<Omit<LabelCreate, "slug">>;

export async function listLabels(): Promise<Label[]> {
  const res = await fetch("/api/labels", { credentials: "include" });
  if (!res.ok) throw new Error(`listLabels ${res.status}`);
  return (await res.json()).labels;
}

export async function createLabel(body: LabelCreate): Promise<Label> {
  const res = await fetch("/api/labels", {
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`createLabel ${res.status}`);
  return res.json();
}

export async function updateLabel(id: number, body: LabelUpdate): Promise<Label> {
  const res = await fetch(`/api/labels/${id}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`updateLabel ${res.status}`);
  return res.json();
}

export async function deleteLabel(id: number): Promise<void> {
  const res = await fetch(`/api/labels/${id}`, { method: "DELETE", credentials: "include" });
  if (!res.ok) throw new Error(`deleteLabel ${res.status}`);
}
