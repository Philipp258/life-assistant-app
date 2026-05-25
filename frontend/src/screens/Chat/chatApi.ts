import type { UIMessage } from "ai";

import { apiFetch, jsonOrThrow } from "@/lib/api";

// Initial-load reads only. Everything live (sending, streaming replies,
// autonomous wakes, slash commands) runs over the one WebSocket — see
// `chatChannel.ts` / `useChatChannel.ts`.

export type MainChat = {
  session_id: number;
  messages: UIMessage[];
};

export async function getMainChat(): Promise<MainChat> {
  const r = await apiFetch("/api/chat/main");
  return jsonOrThrow<MainChat>(r);
}

export async function getChatMessages(
  sessionId: number,
): Promise<UIMessage[]> {
  const r = await apiFetch(`/api/chat/sessions/${sessionId}/messages`);
  const body = await jsonOrThrow<{ session_id: number; messages: UIMessage[] }>(
    r,
  );
  return body.messages;
}

export type SlashCommandSpec = { name: string; description: string };

export async function getSlashCommands(): Promise<SlashCommandSpec[]> {
  const r = await apiFetch("/api/chat/commands");
  const body = await jsonOrThrow<{ commands: SlashCommandSpec[] }>(r);
  return body.commands;
}
