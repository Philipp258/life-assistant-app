import {
  useExternalStoreRuntime,
  type AssistantRuntime,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import { useEffect, useMemo, useRef, useSyncExternalStore } from "react";

import { ChatStore } from "./chatStore";
import { getChatChannel } from "./chatChannel";
import type { WireMessage } from "./convertChatMessage";

function toolNameFromType(type: string): string {
  return type.startsWith("tool-") ? type.slice(5) : type;
}

function stableJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {});
  } catch {
    return "{}";
  }
}

function convertParts(message: WireMessage): Exclude<ThreadMessageLike["content"], string> {
  const parts = (message.parts ?? []) as Array<Record<string, any>>;
  const out: any[] = [];

  for (const part of parts) {
    const type = String(part.type ?? "");
    if (type === "step-start") continue;
    if (message.role === "user" && type === "file") continue;

    if (type === "text") {
      out.push({ type: "text", text: String(part.text ?? "") });
      continue;
    }
    if (type === "reasoning") {
      out.push({ type: "reasoning", text: String(part.text ?? "") });
      continue;
    }
    if (type.startsWith("tool-")) {
      const args = (part.input && typeof part.input === "object" ? part.input : {}) as Record<
        string,
        unknown
      >;
      const isError =
        part.state === "output-error" ||
        part.state === "output-denied" ||
        part.state === "input-error";
      const result =
        part.state === "output-available"
          ? part.output
          : isError
            ? { error: part.errorText ?? part.output ?? "Tool call failed" }
            : undefined;
      out.push({
        type: "tool-call",
        toolName: toolNameFromType(type),
        toolCallId: String(part.toolCallId ?? ""),
        args,
        argsText: stableJson(args),
        result,
        isError,
      });
      continue;
    }
    if (type === "source-url") {
      const url = String(part.url ?? "");
      if (!url) continue;
      out.push({
        type: "source",
        sourceType: "url",
        id: String(part.sourceId ?? part.id ?? url),
        url,
        title: part.title ? String(part.title) : "",
      });
      continue;
    }
    if (type === "file") {
      const url = String(part.url ?? "");
      const mediaType = String(part.mediaType ?? "application/octet-stream");
      if (!url) continue;
      out.push({
        type: "file",
        data: url,
        mimeType: mediaType,
        filename: part.filename ? String(part.filename) : undefined,
      });
      continue;
    }
    if (type.startsWith("data-")) {
      out.push({ type: "data", name: type.slice(5), data: part.data });
    }
  }

  return out as Exclude<ThreadMessageLike["content"], string>;
}

function convertAttachments(message: WireMessage): ThreadMessageLike["attachments"] {
  if (message.role !== "user") return undefined;
  const fileParts = ((message.parts ?? []) as Array<Record<string, any>>).filter(
    (part) => part.type === "file" && typeof part.url === "string",
  );
  if (fileParts.length === 0) return undefined;

  return fileParts.map((part, idx) => {
    const mediaType = String(part.mediaType ?? "application/octet-stream");
    const filename = part.filename ? String(part.filename) : "file";
    const url = String(part.url);
    const isImage = mediaType.startsWith("image/");
    return {
      id: String(idx),
      type: isImage ? ("image" as const) : ("file" as const),
      name: filename,
      contentType: mediaType,
      status: { type: "complete" as const },
      content: [
        isImage
          ? { type: "image" as const, image: url, filename }
          : { type: "file" as const, data: url, mimeType: mediaType, filename },
      ],
    };
  });
}

function convertMetadata(message: WireMessage): ThreadMessageLike["metadata"] {
  const metadata = message.metadata;
  if (!metadata || typeof metadata !== "object") return undefined;
  return { custom: metadata as Record<string, unknown> };
}

function convertCreatedAt(message: WireMessage): Date | undefined {
  const raw = (message as { createdAt?: unknown }).createdAt;
  if (raw instanceof Date) return raw;
  if (typeof raw === "string" || typeof raw === "number") {
    const date = new Date(raw);
    if (!Number.isNaN(date.getTime())) return date;
  }
  return undefined;
}

function convertMessage(message: WireMessage): ThreadMessageLike {
  return {
    id: message.id,
    role: message.role,
    content: convertParts(message),
    attachments: convertAttachments(message),
    metadata: convertMetadata(message),
    createdAt: convertCreatedAt(message),
  };
}

function appendMessageText(message: { content?: unknown }): string {
  const content = message.content;
  if (typeof content === "string") return content.trim();
  if (!Array.isArray(content)) return "";
  return content
    .map((part) => {
      if (!part || typeof part !== "object") return "";
      const p = part as { type?: unknown; text?: unknown };
      return p.type === "text" && typeof p.text === "string" ? p.text : "";
    })
    .join("")
    .trim();
}

export function useChatChannelRuntime({
  sessionId,
  initialMessages,
  voiceActiveRef,
  onLocalSend,
}: {
  sessionId: number;
  initialMessages: WireMessage[];
  voiceActiveRef?: { current: boolean };
  onLocalSend?: () => void;
}): { runtime: AssistantRuntime; messages: WireMessage[]; isRunning: boolean } {
  const store = useMemo(
    () => new ChatStore(sessionId, initialMessages),
    [sessionId], // initialMessages are the cold-start snapshot for this session.
  );
  const channel = useMemo(() => getChatChannel(), []);
  const snapshot = useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    store.getSnapshot,
  );

  const storeRef = useRef(store);
  storeRef.current = store;

  useEffect(() => {
    const remove = channel.addListener((event) => {
      store.dispatch(event);
    });
    channel.subscribe(sessionId);
    return remove;
  }, [channel, sessionId, store]);

  const runtime = useExternalStoreRuntime<WireMessage>({
    messages: snapshot.messages,
    isRunning: snapshot.isRunning,
    convertMessage,
    onNew: async (message: any) => {
      const text = appendMessageText(message);
      if (!text) return;
      if (!/^\/\S+$/.test(text)) onLocalSend?.();
      channel.sendInput(sessionId, text, voiceActiveRef?.current ?? false);
    },
    onCancel: async () => {
      storeRef.current.cancel();
      channel.cancel(sessionId);
    },
    unstable_capabilities: {
      copy: true,
    },
  });

  return {
    runtime,
    messages: snapshot.messages,
    isRunning: snapshot.isRunning,
  };
}

export function useChatSlash(sessionId: number): (name: string) => void {
  const channel = useMemo(() => getChatChannel(), []);
  const ref = useRef(channel);
  ref.current = channel;
  return (name: string) => ref.current.sendSlash(sessionId, name);
}
