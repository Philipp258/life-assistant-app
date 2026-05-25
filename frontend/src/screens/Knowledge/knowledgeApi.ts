import { apiFetch, jsonOrThrow } from "@/lib/api";

export type KnowledgeMeta = {
  path: string;
  title: string;
  id: string;
  created: string;
  updated: string;
  read_only?: boolean;
};

export type Knowledge = KnowledgeMeta & {
  body: string;
};

export type SkillSource = "default" | "user";

export type Skill = {
  name: string;
  description: string;
  path: string;
  source: SkillSource;
};

export type SkillRead = Skill & {
  body: string;
};

export type Folder = {
  path: string;
  items: KnowledgeMeta[];
  folders: string[];
};

export type Tree = {
  folders: Folder[];
};

export type CoreMemoryName = "about_user" | "behavior";

export type KnowledgeMatchField = "title" | "path" | "body";

export type KnowledgeSearchHit = {
  path: string;
  title: string;
  created: string;
  updated: string;
  snippet: string | null;
  matched_in: KnowledgeMatchField[];
  score: number;
};

export async function fetchTree(): Promise<Tree> {
  const r = await apiFetch("/api/knowledge/tree");
  return jsonOrThrow<Tree>(r);
}

/** Search runs on the server (it reads document bodies). A blank query
 * skips the round-trip and returns no hits — the screen falls back to
 * the folder tree. */
export async function searchKnowledge(
  q: string,
): Promise<KnowledgeSearchHit[]> {
  const query = q.trim();
  if (!query) return [];
  const r = await apiFetch(
    `/api/knowledge/search?q=${encodeURIComponent(query)}`,
  );
  const body = await jsonOrThrow<{ hits: KnowledgeSearchHit[] }>(r);
  return body.hits;
}

export async function fetchSkills(): Promise<Skill[]> {
  const r = await apiFetch("/api/skills");
  const body = await jsonOrThrow<{ skills: Skill[] }>(r);
  return body.skills;
}

export async function fetchSkill(name: string): Promise<SkillRead> {
  const r = await apiFetch(`/api/skills/${encodeURIComponent(name)}`);
  return jsonOrThrow<SkillRead>(r);
}

export async function fetchKnowledge(path: string): Promise<Knowledge> {
  const r = await apiFetch(
    `/api/knowledge?path=${encodeURIComponent(path)}`,
  );
  return jsonOrThrow<Knowledge>(r);
}

export async function saveKnowledge(
  path: string,
  body: string,
  title?: string | null,
): Promise<Knowledge> {
  const r = await apiFetch(
    `/api/knowledge?path=${encodeURIComponent(path)}`,
    {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ body, title: title ?? null }),
    },
  );
  return jsonOrThrow<Knowledge>(r);
}

export async function createKnowledge(
  path: string,
  body: string,
  title?: string | null,
): Promise<Knowledge> {
  const r = await apiFetch("/api/knowledge", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ path, body, title: title ?? null }),
  });
  return jsonOrThrow<Knowledge>(r);
}

export async function deleteKnowledge(path: string): Promise<void> {
  const r = await apiFetch(
    `/api/knowledge?path=${encodeURIComponent(path)}`,
    { method: "DELETE" },
  );
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
}

export async function moveKnowledge(
  src: string,
  dst: string,
): Promise<Knowledge> {
  const r = await apiFetch("/api/knowledge/move", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ src, dst }),
  });
  return jsonOrThrow<Knowledge>(r);
}

export async function createFolder(path: string): Promise<{ path: string }> {
  const r = await apiFetch("/api/knowledge/folder", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ path }),
  });
  return jsonOrThrow<{ path: string }>(r);
}

export async function renameFolder(
  src: string,
  dst: string,
): Promise<{ path: string }> {
  const r = await apiFetch("/api/knowledge/folder/rename", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ src, dst }),
  });
  return jsonOrThrow<{ path: string }>(r);
}

export async function deleteFolder(path: string): Promise<void> {
  const r = await apiFetch(
    `/api/knowledge/folder?path=${encodeURIComponent(path)}`,
    { method: "DELETE" },
  );
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
}

export type CoreMemoryRead = { name: string; body: string };

export async function fetchCoreMemory(
  name: CoreMemoryName,
): Promise<CoreMemoryRead> {
  const r = await apiFetch(`/api/core-memory/${name}`);
  return jsonOrThrow<CoreMemoryRead>(r);
}

export async function saveCoreMemory(
  name: CoreMemoryName,
  body: string,
): Promise<CoreMemoryRead> {
  const r = await apiFetch(`/api/core-memory/${name}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ body }),
  });
  return jsonOrThrow<CoreMemoryRead>(r);
}

export function slugify(title: string): string {
  return (
    title
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "untitled"
  );
}
