import { describe, expect, it } from "vitest";

import { tagQueued } from "./useChatChannel";
import type { WireMessage } from "./convertChatMessage";

const msg = (id: string, role: "user" | "assistant"): WireMessage =>
  ({ id, role, parts: [{ type: "text", text: id }] }) as WireMessage;

const queuedIds = (messages: WireMessage[]): string[] =>
  messages
    .filter((m) => (m.metadata as { queued?: unknown } | undefined)?.queued === true)
    .map((m) => m.id);

describe("tagQueued", () => {
  it("does not tag anything while idle", () => {
    const out = tagQueued([msg("a", "assistant"), msg("u", "user")], false, null);
    expect(queuedIds(out)).toEqual([]);
  });

  it("does not tag the message the active turn is answering", () => {
    // Pre-token phase: tail is the user message being processed.
    const out = tagQueued([msg("a", "assistant"), msg("u1", "user")], true, "u1");
    expect(queuedIds(out)).toEqual([]);
  });

  it("tags a follow-up sent after the active turn started", () => {
    const out = tagQueued(
      [msg("a", "assistant"), msg("u1", "user"), msg("u2", "user")],
      true,
      "u1",
    );
    expect(queuedIds(out)).toEqual(["u2"]);
  });

  it("tags the whole trailing block once a draft separates the active message", () => {
    // Streaming draft sits between the answered message and the follow-up.
    const out = tagQueued(
      [msg("u1", "user"), msg("draft", "assistant"), msg("u2", "user")],
      true,
      "u1",
    );
    expect(queuedIds(out)).toEqual(["u2"]);
  });

  it("does not mutate the input messages", () => {
    const input = [msg("a", "assistant"), msg("u1", "user"), msg("u2", "user")];
    tagQueued(input, true, "u1");
    expect(input.every((m) => (m.metadata as unknown) === undefined)).toBe(true);
  });
});
