import { useLayoutEffect, useMemo, useRef, useState, type RefObject } from "react";

import type { WireMessage } from "./convertChatMessage";

const REPLY_TOP_OFFSET = 16;
const MIN_REPLY_SPACER = 180;
const USER_TURN_TAIL = 96;

function lastUserId(messages: WireMessage[]): string | null {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i];
    if (message?.role === "user") return message.id;
  }
  return null;
}

function escapeAttributeValue(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function messageElement(viewport: HTMLElement, messageId: string): HTMLElement | null {
  return viewport.querySelector<HTMLElement>(
    `[data-message-id="${escapeAttributeValue(messageId)}"]`,
  );
}

export function measureReplySpacerHeight(viewport: HTMLElement): number {
  const footer = viewport.querySelector<HTMLElement>(
    '[data-slot="aui_thread-viewport-footer"], [data-slot="aui_task-viewport-footer"]',
  );
  const footerHeight = footer?.getBoundingClientRect().height ?? 0;
  const viewportHeight = viewport.clientHeight || viewport.getBoundingClientRect().height;
  return Math.max(
    MIN_REPLY_SPACER,
    Math.round(viewportHeight - footerHeight - USER_TURN_TAIL),
  );
}

export function scrollMessageToReplyStart(
  viewport: HTMLElement,
  messageId: string,
): boolean {
  const el = messageElement(viewport, messageId);
  if (!el) return false;

  const viewportTop = viewport.getBoundingClientRect().top;
  const messageTop = el.getBoundingClientRect().top - viewportTop;
  viewport.scrollTo({
    top: Math.max(0, viewport.scrollTop + messageTop - REPLY_TOP_OFFSET),
    behavior: "auto",
  });
  return true;
}

export function useLocalSendScroll({
  viewportRef,
  messages,
  localSendVersion,
}: {
  viewportRef: RefObject<HTMLElement | null>;
  messages: WireMessage[];
  localSendVersion: number;
}): number {
  const [spacerHeight, setSpacerHeight] = useState(0);
  const activeVersionRef = useRef(0);
  const baselineUserIdRef = useRef<string | null>(null);
  const scrolledVersionRef = useRef(0);
  const currentLastUserId = useMemo(() => lastUserId(messages), [messages]);

  useLayoutEffect(() => {
    if (messages.length > 0) return;
    activeVersionRef.current = 0;
    baselineUserIdRef.current = null;
    scrolledVersionRef.current = 0;
    setSpacerHeight(0);
  }, [messages.length]);

  useLayoutEffect(() => {
    if (localSendVersion <= activeVersionRef.current) return;

    activeVersionRef.current = localSendVersion;
    baselineUserIdRef.current = currentLastUserId;
    scrolledVersionRef.current = 0;

    const viewport = viewportRef.current;
    setSpacerHeight(viewport ? measureReplySpacerHeight(viewport) : MIN_REPLY_SPACER);
  }, [currentLastUserId, localSendVersion, viewportRef]);

  useLayoutEffect(() => {
    if (activeVersionRef.current !== localSendVersion) return;
    if (!currentLastUserId || currentLastUserId === baselineUserIdRef.current) return;
    if (scrolledVersionRef.current === localSendVersion) return;

    const viewport = viewportRef.current;
    if (!viewport) return;

    setSpacerHeight(measureReplySpacerHeight(viewport));
    scrolledVersionRef.current = localSendVersion;

    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        scrollMessageToReplyStart(viewport, currentLastUserId);
      });
    });
  }, [currentLastUserId, localSendVersion, messages, viewportRef]);

  return spacerHeight;
}
