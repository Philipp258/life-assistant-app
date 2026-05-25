import {
  LoaderIcon,
  MicIcon,
  MicOffIcon,
  PhoneOffIcon,
  SendIcon,
  SquareIcon,
  XIcon,
} from "lucide-react";
import type { FC } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { useVoiceMode } from "./useVoiceMode";

type VoiceMode = ReturnType<typeof useVoiceMode>;

const PHASE_TEXT: Record<VoiceMode["status"]["phase"], string> = {
  idle: "Voice mode off",
  listening: "Listening — pause to send",
  transcribing: "Transcribing…",
  thinking: "Thinking…",
  speaking: "Speaking — say nothing or stop to interrupt",
  error: "Voice mode error",
};

export const VoiceModeBar: FC<{ voice: VoiceMode }> = ({ voice }) => {
  const { phase, errorMessage, ttsAvailable, micUnavailable } = voice.status;
  const micBlocked = phase === "error" && micUnavailable !== null;
  // "Fatal" issues (HTTPS, missing API) won't be fixed by tapping retry.
  // Permission/device issues might be — leave the retry button visible
  // so the user can re-prompt after granting access.
  const canRetry = phase === "error" && (!micUnavailable || !micUnavailable.fatal);
  const phaseLabel = micBlocked ? "Voice mode unavailable" : PHASE_TEXT[phase];

  return (
    <div
      data-slot="aui_voice-mode-bar"
      className="aui-voice-mode-bar flex w-full flex-col gap-2 rounded-(--composer-radius) border bg-background p-(--composer-padding)"
    >
      <div className="flex items-center gap-3 px-1.5 py-1">
        <PhaseIcon phase={phase} micBlocked={micBlocked} />
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="text-sm font-medium text-foreground">
            {phaseLabel}
          </span>
          {errorMessage ? (
            <span className="line-clamp-3 text-xs text-red-500">
              {errorMessage}
            </span>
          ) : !ttsAvailable && phase !== "idle" ? (
            <span className="text-xs text-muted-foreground">
              Read-aloud unavailable in this browser. Transcription still works.
            </span>
          ) : null}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {phase === "listening" && (
            <Button
              type="button"
              size="sm"
              variant="default"
              onClick={voice.submitNow}
              disabled={micBlocked}
              title={micBlocked ? micUnavailable?.message : undefined}
              aria-label="Submit now"
            >
              <SendIcon className="size-4" />
              Submit now
            </Button>
          )}
          {phase === "speaking" && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={voice.stopSpeaking}
              aria-label="Stop speaking"
            >
              <SquareIcon className="size-3 fill-current" />
              Stop speaking
            </Button>
          )}
          {canRetry && (
            <Button
              type="button"
              size="sm"
              variant="default"
              onClick={voice.start}
              aria-label="Try again"
            >
              <MicIcon className="size-4" />
              Try again
            </Button>
          )}
        </div>

        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={voice.stop}
          aria-label="Stop voice mode"
        >
          <PhoneOffIcon className="size-4" />
          Stop
        </Button>
      </div>
    </div>
  );
};

const PhaseIcon: FC<{
  phase: VoiceMode["status"]["phase"];
  micBlocked: boolean;
}> = ({ phase, micBlocked }) => {
  if (phase === "transcribing" || phase === "thinking") {
    return <LoaderIcon className="size-4 animate-spin text-muted-foreground" />;
  }
  if (micBlocked) {
    return <MicOffIcon className="size-4 text-red-500" />;
  }
  if (phase === "error") {
    return <XIcon className="size-4 text-red-500" />;
  }
  return (
    <span
      className={cn(
        "inline-flex size-3 rounded-full",
        phase === "listening" && "animate-pulse bg-red-500",
        phase === "speaking" && "animate-pulse bg-blue-500",
        phase === "idle" && "bg-muted-foreground",
      )}
      aria-hidden
    />
  );
};
