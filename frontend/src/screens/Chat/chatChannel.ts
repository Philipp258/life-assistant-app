// One bidirectional WebSocket to the backend (`/api/ws`), shared by
// every chat surface (main chat + task activity threads). Replaces the
// per-turn streaming POST and the SSE poke. The cookie rides the
// upgrade automatically (same-origin), so there is no auth handshake
// here — the server closes with 4401 if the session is missing.
//
// The channel is dumb on purpose: it forwards typed events and queues
// outbound frames until connected. All correctness (which messages
// exist) lives in the server snapshots; a reconnect simply re-subscribes
// and the server replies with a fresh snapshot per session.

export type ChatWireEvent =
  | { type: "snapshot"; session_id: number; messages: unknown[] }
  | { type: "message_upsert"; session_id: number; message: unknown }
  | { type: "message_delete"; session_id: number; id: string | number }
  | { type: "task_upsert"; session_id: number; task_id: number; task: unknown }
  | { type: "task_delete"; session_id: number; task_id: number }
  | { type: "part_delta"; session_id: number; text: string }
  | { type: "message_start"; session_id: number }
  | { type: "runner_started"; session_id: number }
  | { type: "runner_finished"; session_id: number; outcome?: string }
  | { type: "reset"; session_id: number }
  | { type: string; session_id?: number; [k: string]: unknown };

type Listener = (event: ChatWireEvent) => void;

const RECONNECT_MIN_MS = 500;
const RECONNECT_MAX_MS = 10_000;

class ChatChannel {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private subscribed = new Set<number>();
  private outbox: string[] = [];
  private reconnectMs = RECONNECT_MIN_MS;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private closedByUs = false;

  private url(): string {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}/api/ws`;
  }

  private connect(): void {
    if (
      this.ws &&
      (this.ws.readyState === WebSocket.OPEN ||
        this.ws.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }
    this.closedByUs = false;
    const ws = new WebSocket(this.url());
    this.ws = ws;

    ws.onopen = () => {
      this.reconnectMs = RECONNECT_MIN_MS;
      // Re-subscribe everything; the server answers each with a fresh
      // snapshot, which is the connect/reconnect resync.
      if (this.subscribed.size > 0) {
        this.raw({
          type: "subscribe",
          session_ids: [...this.subscribed],
        });
      }
      const pending = this.outbox;
      this.outbox = [];
      for (const frame of pending) ws.send(frame);
    };

    ws.onmessage = (e) => {
      let parsed: ChatWireEvent;
      try {
        parsed = JSON.parse(e.data as string);
      } catch {
        return;
      }
      if (!parsed || typeof parsed !== "object") return;
      for (const fn of [...this.listeners]) {
        try {
          fn(parsed);
        } catch {
          // A listener throwing must not take down the socket.
        }
      }
    };

    ws.onclose = () => {
      this.ws = null;
      if (this.closedByUs || this.listeners.size === 0) return;
      this.scheduleReconnect();
    };

    ws.onerror = () => {
      // `onclose` fires after `onerror`; reconnect is handled there.
      ws.close();
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer != null) return;
    const delay = this.reconnectMs;
    this.reconnectMs = Math.min(this.reconnectMs * 2, RECONNECT_MAX_MS);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private raw(payload: Record<string, unknown>): void {
    const frame = JSON.stringify(payload);
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(frame);
    } else {
      this.outbox.push(frame);
      this.connect();
    }
  }

  addListener(fn: Listener): () => void {
    this.listeners.add(fn);
    this.connect();
    return () => {
      this.listeners.delete(fn);
    };
  }

  subscribe(sessionId: number): void {
    this.subscribed.add(sessionId);
    this.raw({ type: "subscribe", session_ids: [sessionId] });
  }

  resync(sessionId: number): void {
    this.raw({ type: "resync", session_id: sessionId });
  }

  sendInput(sessionId: number, text: string, voice: boolean): void {
    this.raw({ type: "input", session_id: sessionId, text, voice });
  }

  sendSlash(sessionId: number, name: string): void {
    this.raw({ type: "slash", session_id: sessionId, name });
  }

  cancel(sessionId: number): void {
    this.raw({ type: "cancel", session_id: sessionId });
  }
}

let singleton: ChatChannel | null = null;

export function getChatChannel(): ChatChannel {
  if (singleton == null) singleton = new ChatChannel();
  return singleton;
}

export type { ChatChannel };
