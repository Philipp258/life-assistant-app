import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { PhoneIcon, PhoneOffIcon } from "lucide-react";
import { useEffect, useRef, useState, type MutableRefObject } from "react";

import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";
import { Thread } from "@/components/assistant-ui/thread";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useIdentity } from "@/shell/identity";

import { getMainChat } from "./chatApi";
import type { WireMessage } from "./convertChatMessage";
import { useChatChannelRuntime, useChatSlash } from "./useChatChannel";
import { useLocalSendScroll } from "./useLocalSendScroll";
import { useVoiceMode } from "./voice/useVoiceMode";
import { VoiceModeBar } from "./voice/VoiceModeBar";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; sessionId: number; messages: WireMessage[] }
  | { kind: "error"; message: string };

export function ChatScreen({ isVisible = true }: { isVisible?: boolean } = {}) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    getMainChat()
      .then(({ session_id, messages }) => {
        if (!cancelled)
          setState({
            kind: "ready",
            sessionId: session_id,
            messages: messages as WireMessage[],
          });
      })
      .catch((e) => {
        if (!cancelled)
          setState({
            kind: "error",
            message: e instanceof Error ? e.message : String(e),
          });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.kind === "loading")
    return (
      <div className="flex h-full items-center justify-center text-sm text-life-ink-3">
        Loading…
      </div>
    );
  if (state.kind === "error")
    return (
      <div className="flex h-full items-center justify-center px-6 text-center text-sm text-red-500">
        Couldn't load chat: {state.message}
      </div>
    );

  return (
    <ChatRuntime
      key={state.sessionId}
      sessionId={state.sessionId}
      initialMessages={state.messages}
      isVisible={isVisible}
    />
  );
}

function ChatRuntime({
  sessionId,
  initialMessages,
  isVisible,
}: {
  sessionId: number;
  initialMessages: WireMessage[];
  isVisible: boolean;
}) {
  const voiceActiveRef = useRef(false);
  const [localSendVersion, setLocalSendVersion] = useState(0);
  const onSlashCommand = useChatSlash(sessionId);
  const { runtime, messages } = useChatChannelRuntime({
    sessionId,
    initialMessages,
    voiceActiveRef,
    onLocalSend: () => setLocalSendVersion((version) => version + 1),
  });

  return (
    <TooltipProvider>
      <AssistantRuntimeProvider runtime={runtime}>
        <ChatRuntimeBody
          onSlashCommand={onSlashCommand}
          voiceActiveRef={voiceActiveRef}
          isVisible={isVisible}
          messages={messages}
          localSendVersion={localSendVersion}
        />
      </AssistantRuntimeProvider>
    </TooltipProvider>
  );
}

function ChatRuntimeBody({
  onSlashCommand,
  voiceActiveRef,
  isVisible,
  messages,
  localSendVersion,
}: {
  onSlashCommand: (name: string) => void;
  voiceActiveRef: MutableRefObject<boolean>;
  isVisible: boolean;
  messages: WireMessage[];
  localSendVersion: number;
}) {
  const { assistantName } = useIdentity();
  const voice = useVoiceMode();
  const voiceActive = voice.status.active;
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const replySpacerHeight = useLocalSendScroll({
    viewportRef,
    messages,
    localSendVersion,
  });

  useEffect(() => {
    voiceActiveRef.current = voiceActive;
  }, [voiceActive, voiceActiveRef]);

  useEffect(() => {
    if (!isVisible) return;
    const viewport = viewportRef.current;
    if (!viewport) return;
    const scrollToBottom = () => {
      viewport.scrollTop = viewport.scrollHeight;
    };
    scrollToBottom();
    requestAnimationFrame(scrollToBottom);
  }, [isVisible]);

  return (
    <div className="flex h-full flex-col bg-life-bg">
      <header className="flex items-center justify-between gap-3 border-b border-life-line px-4 py-3">
        <span className="text-sm font-semibold text-life-ink shrink-0">
          {assistantName}
        </span>
        <TooltipIconButton
          tooltip={voiceActive ? "Stop voice mode" : "Start voice mode"}
          side="bottom"
          aria-label={voiceActive ? "Stop voice mode" : "Start voice mode"}
          variant={voiceActive ? "default" : "ghost"}
          onClick={voice.toggle}
        >
          {voiceActive ? (
            <PhoneOffIcon className="size-4" />
          ) : (
            <PhoneIcon className="size-4" />
          )}
        </TooltipIconButton>
      </header>
      <div className="flex-1 overflow-hidden">
        <Thread
          onSlashCommand={onSlashCommand}
          composerSlot={voiceActive ? <VoiceModeBar voice={voice} /> : undefined}
          viewportRef={viewportRef}
          replySpacerHeight={replySpacerHeight}
        />
      </div>
    </div>
  );
}
