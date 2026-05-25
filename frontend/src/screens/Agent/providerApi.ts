import { apiFetch, jsonOrThrow } from "@/lib/api";

export type ChatProvider =
  | "openai"
  | "openrouter"
  | "zai"
  | "codex";

export type OpenAIBlock = { configured: boolean; chat_model: string | null };
export type OpenRouterBlock = {
  configured: boolean;
  chat_model: string | null;
  tts_model: string | null;
  tts_voice: string | null;
};
export type ZAIBlock = {
  configured: boolean;
  endpoint: string | null;
  chat_model: string | null;
};
export type CodexBlock = { configured: boolean; chat_model: string | null };

export type ProviderSettings = {
  preferred_chat_provider: ChatProvider | null;
  openai: OpenAIBlock;
  openrouter: OpenRouterBlock;
  zai: ZAIBlock;
  codex: CodexBlock;
};

export type OpenAIPatch = { api_key?: string | null; chat_model?: string | null };
export type OpenRouterPatch = {
  api_key?: string | null;
  chat_model?: string | null;
  tts_model?: string | null;
  tts_voice?: string | null;
};
export type ZAIPatch = {
  api_key?: string | null;
  endpoint?: string | null;
  chat_model?: string | null;
};
export type CodexPatch = { auth_json?: string | null; chat_model?: string | null };

export async function getProviderSettings(): Promise<ProviderSettings> {
  const r = await apiFetch("/api/settings/providers");
  return jsonOrThrow<ProviderSettings>(r);
}

async function putOrThrow<T>(path: string, body: unknown): Promise<T> {
  const r = await apiFetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const detail = await r
      .json()
      .then((b: { detail?: string }) => b.detail)
      .catch(() => undefined);
    throw new Error(detail ?? `${r.status} ${r.statusText}`);
  }
  return (await r.json()) as T;
}

export function putOpenAI(patch: OpenAIPatch) {
  return putOrThrow<ProviderSettings>("/api/settings/providers/openai", patch);
}

export function putOpenRouter(patch: OpenRouterPatch) {
  return putOrThrow<ProviderSettings>("/api/settings/providers/openrouter", patch);
}

export function putZAI(patch: ZAIPatch) {
  return putOrThrow<ProviderSettings>("/api/settings/providers/zai", patch);
}

export function putCodex(patch: CodexPatch) {
  return putOrThrow<ProviderSettings>("/api/settings/providers/codex", patch);
}

export function putPreferredChat(preferred: ChatProvider | null) {
  return putOrThrow<ProviderSettings>("/api/settings/providers/preferred-chat", {
    preferred_chat_provider: preferred,
  });
}
