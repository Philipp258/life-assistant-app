import { render } from "@testing-library/react";
import { useRef, type RefObject } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WireMessage } from "./convertChatMessage";
import {
  measureReplySpacerHeight,
  scrollMessageToReplyStart,
  useLocalSendScroll,
} from "./useLocalSendScroll";

const rect = (top: number, height = 40): DOMRect =>
  ({
    top,
    bottom: top + height,
    left: 0,
    right: 320,
    width: 320,
    height,
    x: 0,
    y: top,
    toJSON: () => ({}),
  }) as DOMRect;

const msg = (
  id: string,
  role: "user" | "assistant",
  top = 0,
): WireMessage =>
  ({
    id,
    role,
    parts: [{ type: "text", text: id }],
    metadata: { testTop: top },
  }) as WireMessage;

function defineReadonly<T extends object, K extends keyof T>(
  object: T,
  key: K,
  value: T[K],
) {
  Object.defineProperty(object, key, {
    configurable: true,
    value,
  });
}

describe("local send scroll helpers", () => {
  it("measures deterministic reply spacer room", () => {
    const viewport = document.createElement("div");
    defineReadonly(viewport, "clientHeight", 640);
    const footer = document.createElement("div");
    footer.dataset.slot = "aui_thread-viewport-footer";
    footer.getBoundingClientRect = () => rect(540, 120);
    viewport.append(footer);

    expect(measureReplySpacerHeight(viewport)).toBe(424);
  });

  it("scrolls the sent user message to the reply start", () => {
    const viewport = document.createElement("div");
    viewport.scrollTop = 200;
    viewport.getBoundingClientRect = () => rect(0, 600);
    (viewport as any).scrollTo = vi.fn((options: ScrollToOptions = {}) => {
      viewport.scrollTop = Number(options.top);
    });

    const message = document.createElement("div");
    message.dataset.messageId = "42";
    message.getBoundingClientRect = () => rect(500, 48);
    viewport.append(message);

    expect(scrollMessageToReplyStart(viewport, "42")).toBe(true);
    expect(viewport.scrollTo).toHaveBeenCalledWith({
      top: 684,
      behavior: "auto",
    });
    expect(viewport.scrollTop).toBe(684);
  });
});

const scrollCalls: number[] = [];

function Harness({
  messages,
  localSendVersion,
}: {
  messages: WireMessage[];
  localSendVersion: number;
}) {
  const viewportRef = useRef<HTMLElement | null>(null);
  const spacerHeight = useLocalSendScroll({
    viewportRef: viewportRef as RefObject<HTMLElement | null>,
    messages,
    localSendVersion,
  });

  return (
    <div
      data-testid="viewport"
      ref={(el) => {
        if (!el) return;
        viewportRef.current = el;
        defineReadonly(el, "clientHeight", 640);
        el.scrollTop = 200;
        el.getBoundingClientRect = () => rect(0, 640);
        (el as any).scrollTo = (options: ScrollToOptions = {}) => {
          scrollCalls.push(Number(options.top));
          el.scrollTop = Number(options.top);
        };
      }}
    >
      {messages.map((message) => (
        <div
          key={message.id}
          data-message-id={message.id}
          data-role={message.role}
          ref={(el) => {
            if (!el) return;
            const top = Number(
              (message.metadata as { testTop?: unknown } | undefined)?.testTop ?? 0,
            );
            el.getBoundingClientRect = () => rect(top, 48);
          }}
        />
      ))}
      <div
        data-slot="aui_thread-viewport-footer"
        ref={(el) => {
          if (!el) return;
          el.getBoundingClientRect = () => rect(520, 120);
        }}
      />
      <div data-testid="spacer" style={{ height: spacerHeight }} />
    </div>
  );
}

describe("useLocalSendScroll", () => {
  beforeEach(() => {
    scrollCalls.length = 0;
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      cb(0);
      return 1;
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("does not scroll for server-initiated assistant updates", () => {
    const { rerender } = render(
      <Harness
        messages={[msg("1", "assistant", 120)]}
        localSendVersion={0}
      />,
    );

    rerender(
      <Harness
        messages={[msg("1", "assistant", 120), msg("2", "assistant", 180)]}
        localSendVersion={0}
      />,
    );

    expect(scrollCalls).toEqual([]);
  });

  it("scrolls once when the locally sent user row is echoed", () => {
    const { rerender, getByTestId } = render(
      <Harness
        messages={[msg("1", "assistant", 120)]}
        localSendVersion={0}
      />,
    );

    rerender(
      <Harness
        messages={[msg("1", "assistant", 120)]}
        localSendVersion={1}
      />,
    );
    expect(getByTestId("spacer")).toHaveStyle({ height: "424px" });
    expect(scrollCalls).toEqual([]);

    rerender(
      <Harness
        messages={[msg("1", "assistant", 120), msg("2", "user", 500)]}
        localSendVersion={1}
      />,
    );

    expect(scrollCalls).toEqual([684]);

    rerender(
      <Harness
        messages={[
          msg("1", "assistant", 120),
          msg("2", "user", 500),
          msg("3", "assistant", 560),
        ]}
        localSendVersion={1}
      />,
    );

    expect(scrollCalls).toEqual([684]);

    rerender(
      <Harness
        messages={[
          msg("1", "assistant", 120),
          msg("2", "user", 500),
          msg("3", "assistant", 560),
        ]}
        localSendVersion={1}
      />,
    );

    expect(getByTestId("spacer")).toHaveStyle({ height: "424px" });
    expect(scrollCalls).toEqual([684]);
  });

  it("clears stale spacer on reset", () => {
    const { rerender, getByTestId } = render(
      <Harness
        messages={[msg("1", "assistant", 120)]}
        localSendVersion={1}
      />,
    );

    expect(getByTestId("spacer")).toHaveStyle({ height: "424px" });

    rerender(
      <Harness
        messages={[]}
        localSendVersion={1}
      />,
    );

    expect(getByTestId("spacer")).toHaveStyle({ height: "0px" });
  });
});
