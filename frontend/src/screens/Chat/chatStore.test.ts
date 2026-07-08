import { describe, expect, it } from "vitest";

import { ChatStore } from "./chatStore";
import type { ChatWireEvent } from "./chatChannel";
import type { WireMessage } from "./convertChatMessage";

const msg = (
  id: string,
  role: "user" | "assistant",
  text = id,
  createdAt?: string,
): WireMessage =>
  ({
    id,
    role,
    parts: [{ type: "text", text }],
    ...(createdAt ? { createdAt } : {}),
  }) as WireMessage;

function ids(store: ChatStore): string[] {
  return store.getSnapshot().messages.map((message) => message.id);
}

describe("ChatStore", () => {
  it("replaces committed messages from snapshots and sorts stable numeric ids", () => {
    const store = new ChatStore(7, [msg("2", "assistant"), msg("1", "user")]);

    expect(ids(store)).toEqual(["1", "2"]);

    store.dispatch({
      type: "snapshot",
      session_id: 7,
      messages: [msg("4", "assistant"), msg("3", "user")],
    });

    expect(ids(store)).toEqual(["3", "4"]);
  });

  it("does not add an empty assistant spacer before text arrives", () => {
    const store = new ChatStore(7, [msg("1", "user", "hello")]);

    store.dispatch({ type: "runner_started", session_id: 7, run_id: "abc" } as ChatWireEvent);
    expect(store.getSnapshot().isRunning).toBe(true);
    expect(ids(store)).toEqual(["1"]);

    store.dispatch({ type: "message_start", session_id: 7, run_id: "abc" } as ChatWireEvent);
    expect(ids(store)).toEqual(["1"]);
  });

  it("keeps fallback live deltas as an ephemeral assistant overlay", () => {
    const store = new ChatStore(7, [msg("1", "user", "hello")]);

    store.dispatch({ type: "runner_started", session_id: 7, run_id: "abc" } as ChatWireEvent);

    store.dispatch({ type: "part_delta", session_id: 7, run_id: "abc", text: "He" });
    store.dispatch({ type: "part_delta", session_id: 7, run_id: "abc", text: "Hello" });

    const draft = store.getSnapshot().messages.at(-1);
    expect(draft?.id).toBe("run-abc");
    expect(draft?.parts?.[0]).toMatchObject({ type: "text", text: "Hello" });
  });

  it("drops the overlay when committed assistant output arrives", () => {
    const store = new ChatStore(7, [msg("1", "user")]);
    store.dispatch({ type: "runner_started", session_id: 7, run_id: "abc" } as ChatWireEvent);
    store.dispatch({ type: "part_delta", session_id: 7, run_id: "abc", text: "draft" });

    store.dispatch({
      type: "snapshot",
      session_id: 7,
      messages: [msg("1", "user"), msg("2", "assistant", "committed")],
    });

    expect(ids(store)).toEqual(["1", "2"]);
    expect(store.getSnapshot().isRunning).toBe(true);
  });

  it("clears running state and ignores other sessions", () => {
    const store = new ChatStore(7, [msg("1", "user")]);
    store.dispatch({ type: "runner_started", session_id: 7, run_id: "abc" } as ChatWireEvent);
    store.dispatch({ type: "part_delta", session_id: 99, text: "wrong" } as ChatWireEvent);
    expect(ids(store)).toEqual(["1"]);

    store.dispatch({ type: "runner_finished", session_id: 7 } as ChatWireEvent);
    expect(store.getSnapshot()).toMatchObject({
      isRunning: false,
      messages: [{ id: "1" }],
    });
  });

  it("supports committed upsert and delete events", () => {
    const store = new ChatStore(7, [msg("1", "user")]);

    store.dispatch({
      type: "message_upsert",
      session_id: 7,
      message: msg("2", "assistant"),
    } as ChatWireEvent);
    expect(ids(store)).toEqual(["1", "2"]);

    store.dispatch({ type: "message_delete", session_id: 7, id: "1" } as ChatWireEvent);
    expect(ids(store)).toEqual(["2"]);
  });

  it("orders mixed roles by createdAt before numeric row id", () => {
    const store = new ChatStore(7, [
      msg("1", "user", "first user", "2026-05-17T12:00:00Z"),
      msg("2", "user", "second user", "2026-05-17T12:02:00Z"),
      msg("3", "assistant", "first assistant", "2026-05-17T12:01:00Z"),
      msg("4", "assistant", "second assistant", "2026-05-17T12:03:00Z"),
    ]);

    expect(ids(store)).toEqual(["1", "3", "2", "4"]);
  });

  it("falls back to numeric ids for messages without createdAt", () => {
    const store = new ChatStore(7, [
      msg("3", "assistant", "missing timestamp"),
      msg("2", "user", "known timestamp", "2026-05-17T12:02:00Z"),
      msg("1", "user", "older missing timestamp"),
    ]);

    expect(ids(store)).toEqual(["1", "2", "3"]);
  });

  it("falls back to numeric ids when timestamps are equal", () => {
    const store = new ChatStore(7, [
      msg("2", "assistant", "same time assistant", "2026-05-17T12:00:00Z"),
      msg("1", "user", "same time user", "2026-05-17T12:00:00Z"),
    ]);

    expect(ids(store)).toEqual(["1", "2"]);
  });

  it("keeps task-source assistant upserts in chronological position", () => {
    const store = new ChatStore(7, [
      msg("1", "user", "normal user", "2026-05-17T12:00:00Z"),
      msg("2", "user", "next user", "2026-05-17T12:02:00Z"),
    ]);

    store.dispatch({
      type: "message_upsert",
      session_id: 7,
      message: {
        ...msg("3", "assistant", "background task reply", "2026-05-17T12:01:00Z"),
        metadata: {
          source: {
            type: "task",
            task_id: 9,
            task_title: "Background task",
            source_session_id: 11,
          },
        },
      },
    } as ChatWireEvent);

    expect(ids(store)).toEqual(["1", "3", "2"]);
  });

  it("adopts run state from a snapshot that carries is_running", () => {
    const store = new ChatStore(7, [msg("1", "user")]);
    store.dispatch({ type: "runner_started", session_id: 7, run_id: "abc" } as ChatWireEvent);
    expect(store.getSnapshot().isRunning).toBe(true);

    // A reconnect snapshot reporting the turn is done heals the stuck
    // spinner even though no runner_finished was ever observed.
    store.dispatch({
      type: "snapshot",
      session_id: 7,
      messages: [msg("1", "user"), msg("2", "assistant")],
      is_running: false,
    } as ChatWireEvent);

    expect(store.getSnapshot().isRunning).toBe(false);
  });

  it("leaves run state untouched when a snapshot omits is_running", () => {
    const store = new ChatStore(7, [msg("1", "user")]);
    store.dispatch({ type: "runner_started", session_id: 7, run_id: "abc" } as ChatWireEvent);

    store.dispatch({
      type: "snapshot",
      session_id: 7,
      messages: [msg("1", "user")],
    });

    expect(store.getSnapshot().isRunning).toBe(true);
  });

  it("tracks the active user id at the turn boundary", () => {
    const store = new ChatStore(7, [msg("1", "user"), msg("2", "user")]);
    store.dispatch({ type: "runner_started", session_id: 7, run_id: "abc" } as ChatWireEvent);

    expect(store.getSnapshot().activeUserId).toBe("2");
  });

  it("treats the tail as active when a snapshot starts a run on reconnect", () => {
    const store = new ChatStore(7, [msg("1", "user")]);

    store.dispatch({
      type: "snapshot",
      session_id: 7,
      messages: [msg("1", "user")],
      is_running: true,
    } as ChatWireEvent);

    expect(store.getSnapshot()).toMatchObject({ isRunning: true, activeUserId: "1" });
  });

  it("ignores redundant snapshots and upserts without notifying subscribers", () => {
    const store = new ChatStore(7, [msg("1", "user", "hello")]);
    let notified = 0;
    store.subscribe(() => {
      notified += 1;
    });

    store.dispatch({
      type: "snapshot",
      session_id: 7,
      messages: [msg("1", "user", "hello")],
    });
    store.dispatch({
      type: "message_upsert",
      session_id: 7,
      message: msg("1", "user", "hello"),
    } as ChatWireEvent);

    expect(notified).toBe(0);
  });
});
