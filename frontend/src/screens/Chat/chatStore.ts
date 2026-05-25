import type { ChatWireEvent } from "./chatChannel";
import type { WireMessage } from "./convertChatMessage";

export type ChatStoreSnapshot = {
  messages: WireMessage[];
  isRunning: boolean;
};

type Listener = () => void;

function cloneMessage(message: WireMessage): WireMessage {
  return {
    ...message,
    parts: message.parts ? message.parts.map((part) => ({ ...part })) : [],
  };
}

function sameJson(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  try {
    return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
  } catch {
    return false;
  }
}

function sameMessage(a: WireMessage, b: WireMessage): boolean {
  const aCreatedAt = (a as { createdAt?: unknown }).createdAt ?? null;
  const bCreatedAt = (b as { createdAt?: unknown }).createdAt ?? null;
  return (
    a.id === b.id &&
    a.role === b.role &&
    sameJson(a.parts ?? [], b.parts ?? []) &&
    sameJson(a.metadata ?? null, b.metadata ?? null) &&
    sameJson(aCreatedAt, bCreatedAt)
  );
}

function sameMessageRefs(a: WireMessage[], b: WireMessage[]): boolean {
  return a.length === b.length && a.every((message, index) => message === b[index]);
}

function numericId(message: WireMessage): number | null {
  const n = Number(message.id);
  return Number.isFinite(n) ? n : null;
}

function createdAtMs(message: WireMessage): number | null {
  const raw = (message as { createdAt?: unknown }).createdAt;
  if (raw instanceof Date) {
    const n = raw.getTime();
    return Number.isFinite(n) ? n : null;
  }
  if (typeof raw === "string" || typeof raw === "number") {
    const n = new Date(raw).getTime();
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function sortCommitted(messages: WireMessage[]): WireMessage[] {
  return messages
    .map((message, index) => ({ message, index }))
    .sort((a, b) => {
      const at = createdAtMs(a.message);
      const bt = createdAtMs(b.message);
      if (at != null && bt != null && at !== bt) return at - bt;

      const an = numericId(a.message);
      const bn = numericId(b.message);
      if (an != null && bn != null && an !== bn) return an - bn;
      if (an != null && bn == null) return -1;
      if (an == null && bn != null) return 1;
      return a.index - b.index;
    })
    .map((item) => item.message);
}

function textDraft(runId: string, text: string): WireMessage {
  return {
    id: `run-${runId}`,
    role: "assistant",
    parts: text ? [{ type: "text", text }] : [],
    createdAt: new Date(),
    metadata: { transient: true },
  } as WireMessage;
}

export class ChatStore {
  private committed: WireMessage[];
  private draft: WireMessage | null = null;
  private running = false;
  private runId = "pending";
  private snapshot: ChatStoreSnapshot;
  private listeners = new Set<Listener>();

  constructor(
    private readonly sessionId: number,
    initialMessages: WireMessage[],
  ) {
    this.committed = sortCommitted(initialMessages.map(cloneMessage));
    this.snapshot = { messages: this.committed, isRunning: false };
  }

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getSnapshot = (): ChatStoreSnapshot => this.snapshot;

  dispatch(event: ChatWireEvent): void {
    if (event.session_id !== this.sessionId) return;

    switch (event.type) {
      case "snapshot":
        this.replaceCommitted(
          Array.isArray(event.messages) ? (event.messages as WireMessage[]) : [],
        );
        return;
      case "message_upsert":
        this.upsertCommitted(
          event as ChatWireEvent & {
            message?: unknown;
            id?: unknown;
            role?: unknown;
            parts?: unknown;
            metadata?: unknown;
          },
        );
        return;
      case "message_delete":
        this.deleteCommitted(event as ChatWireEvent & { id?: unknown });
        return;
      case "reset":
        this.committed = [];
        this.draft = null;
        this.running = false;
        this.recompute();
        return;
      case "runner_started":
        this.running = true;
        this.runId = String((event as { run_id?: unknown }).run_id ?? Date.now());
        this.recompute();
        return;
      case "message_start":
        this.running = true;
        this.runId = String((event as { run_id?: unknown }).run_id ?? this.runId);
        this.recompute();
        return;
      case "part_delta": {
        const text = typeof event.text === "string" ? event.text : "";
        this.running = true;
        this.runId = String((event as { run_id?: unknown }).run_id ?? this.runId);
        this.draft = text ? textDraft(this.runId, text) : null;
        this.recompute();
        return;
      }
      case "runner_finished":
        this.running = false;
        this.draft = null;
        this.recompute();
        return;
    }
  }

  cancel(): void {
    this.running = false;
    this.draft = null;
    this.recompute();
  }

  private replaceCommitted(messages: WireMessage[]): void {
    const previousById = new Map(this.committed.map((message) => [message.id, message]));
    const next = sortCommitted(
      messages.map((message) => {
        const previous = previousById.get(message.id);
        return previous && sameMessage(previous, message) ? previous : cloneMessage(message);
      }),
    );
    const committedChanged = !sameMessageRefs(this.committed, next);
    this.committed = next;
    if (
      !this.running ||
      this.committed.length === 0 ||
      this.committed.at(-1)?.role === "assistant"
    ) {
      this.draft = null;
    }
    this.recompute(committedChanged);
  }

  private upsertCommitted(
    event: ChatWireEvent & {
      message?: unknown;
      id?: unknown;
      role?: unknown;
      parts?: unknown;
      metadata?: unknown;
    },
  ): void {
    const message =
      event.message ??
      (event.id && event.role
        ? {
            id: String(event.id),
            role: event.role,
            parts: Array.isArray(event.parts) ? event.parts : [],
            metadata: event.metadata,
          }
        : null);
    if (!message || typeof message !== "object") return;
    const incoming = message as WireMessage;
    const idx = this.committed.findIndex((m) => m.id === incoming.id);
    const next =
      idx >= 0 && sameMessage(this.committed[idx], incoming)
        ? this.committed[idx]
        : cloneMessage(incoming);
    const previousCommitted = this.committed;
    if (idx >= 0) {
      this.committed = [
        ...this.committed.slice(0, idx),
        next,
        ...this.committed.slice(idx + 1),
      ];
    } else {
      this.committed = [...this.committed, next];
    }
    this.committed = sortCommitted(this.committed);
    if (next.role === "assistant") this.draft = null;
    this.recompute(!sameMessageRefs(previousCommitted, this.committed));
  }

  private deleteCommitted(event: ChatWireEvent & { id?: unknown }): void {
    const id = String(event.id ?? "");
    if (!id) return;
    this.committed = this.committed.filter((m) => m.id !== id);
    this.recompute();
  }

  private recompute(force = false): void {
    const messages = this.draft ? [...this.committed, this.draft] : this.committed;
    if (
      !force &&
      this.snapshot.isRunning === this.running &&
      sameMessageRefs(this.snapshot.messages, messages)
    ) {
      return;
    }
    this.snapshot = { messages, isRunning: this.running };
    for (const listener of [...this.listeners]) listener();
  }
}
