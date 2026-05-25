import { useAui, useAuiState } from "@assistant-ui/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  DEFAULT_VOICE_PLAYBACK_SPEED,
  getRuntimeSettings,
  parseVoicePlaybackSpeed,
} from "../../Agent/runtimeSettingsApi";
import { cleanForSpeech, useSpeechPlayback } from "./useSpeechPlayback";
import {
  detectStaticMicAvailability,
  type MicUnavailable,
  useVoiceRecorder,
} from "./useVoiceRecorder";
import { transcribeAudio } from "./voiceApi";

export type VoiceModePhase =
  | "idle"
  | "listening"
  | "transcribing"
  | "thinking"
  | "speaking"
  | "error";

export type VoiceModeStatus = {
  active: boolean;
  phase: VoiceModePhase;
  errorMessage: string | null;
  ttsAvailable: boolean;
  /**
   * Set when the mic can't be used at all (HTTPS, missing API, denied
   * permission, …). When non-null the bar should hide retry affordances
   * and offer "Type instead" / "Stop" only.
   */
  micUnavailable: MicUnavailable | null;
};

type AssistantMessageLike = {
  id: string;
  role: string;
  parts?: unknown;
};

const DEFAULT_VAD_TIMEOUT_MS = 4_000;
const MIN_VAD_TIMEOUT_MS = 250;
const MAX_VAD_TIMEOUT_MS = 30_000;

function parseVadTimeoutMs(value: string | null | undefined): number {
  if (!value) return DEFAULT_VAD_TIMEOUT_MS;
  if (!/^\d+$/.test(value)) return DEFAULT_VAD_TIMEOUT_MS;
  const timeoutMs = Number.parseInt(value, 10);
  return Math.min(MAX_VAD_TIMEOUT_MS, Math.max(MIN_VAD_TIMEOUT_MS, timeoutMs));
}

function extractTextFromParts(parts: unknown): string {
  if (!Array.isArray(parts)) return "";
  const chunks: string[] = [];
  for (const part of parts) {
    if (!part || typeof part !== "object") continue;
    const p = part as { type?: unknown; text?: unknown };
    if (p.type === "text" && typeof p.text === "string") {
      chunks.push(p.text);
    }
  }
  return chunks.join("\n").trim();
}

function lastAssistantMessage(
  messages: ReadonlyArray<unknown>,
): AssistantMessageLike | null {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const m = messages[i] as AssistantMessageLike | undefined;
    if (m && m.role === "assistant") return m;
  }
  return null;
}

/**
 * Split `text` into complete sentences plus the number of characters
 * consumed. A sentence counts as complete only once its terminator
 * (.?!… and any closing quote/bracket) is followed by whitespace —
 * while the reply is still streaming that means the *next* sentence has
 * begun, so the finished one is safe to speak. Trailing text with no
 * terminator-then-space stays unconsumed for the next tick (or the
 * end-of-turn flush).
 */
export function takeSentences(text: string): {
  sentences: string[];
  consumed: number;
} {
  const sentences: string[] = [];
  let consumed = 0;
  const re = /[.!?…]+["'”’)\]]*\s+/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const end = m.index + m[0].length;
    const chunk = text.slice(consumed, end).trim();
    if (chunk) sentences.push(chunk);
    consumed = end;
  }
  return { sentences, consumed };
}

/**
 * Drive the voice mode loop: record → transcribe → submit → wait →
 * speak → record. Uses the assistant-ui runtime's composer to submit
 * the transcript through the normal chat path so persistence and SSE
 * fan-out work without any special casing on the backend.
 *
 * Must be mounted inside an `AssistantRuntimeProvider` — the hook
 * relies on `useAui` / `useAuiState` to drive the composer and observe
 * the assistant's running state.
 */
export function useVoiceMode(): {
  status: VoiceModeStatus;
  start: () => void;
  stop: () => void;
  submitNow: () => void;
  cancelRecording: () => void;
  stopSpeaking: () => void;
  toggle: () => void;
} {
  const aui = useAui();
  const isRunning = useAuiState((s) => s.thread.isRunning);
  const messageCount = useAuiState((s) => s.thread.messages.length);
  // Re-renders as the in-progress assistant reply grows token by token,
  // so the streaming effect can speak each sentence as it completes
  // instead of waiting for the whole turn.
  const streamText = useAuiState((s) => {
    const target = lastAssistantMessage(s.thread.messages);
    return target ? extractTextFromParts(target.parts) : "";
  });

  const [active, setActive] = useState(false);
  const [phase, setPhase] = useState<VoiceModePhase>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [micUnavailable, setMicUnavailable] = useState<MicUnavailable | null>(
    null,
  );
  const [vadTimeoutMs, setVadTimeoutMs] = useState(DEFAULT_VAD_TIMEOUT_MS);
  const [voicePlaybackSpeed, setVoicePlaybackSpeed] = useState(
    DEFAULT_VOICE_PLAYBACK_SPEED,
  );
  // Pre-flight: known synchronously at mount, doesn't change during a session.
  const staticUnavailable = useMemo(() => detectStaticMicAvailability(), []);

  const activeRef = useRef(active);
  activeRef.current = active;
  const phaseRef = useRef(phase);
  phaseRef.current = phase;

  // Snapshot of message IDs at the moment we sent a transcript. The
  // first assistant message *after* this snapshot is the one we'll
  // read aloud once isRunning settles back to false.
  const baselineIdsRef = useRef<Set<string>>(new Set());
  const lastSpokenIdRef = useRef<string | null>(null);
  const wasRunningRef = useRef(isRunning);
  // Bumped whenever we abandon an in-flight transcription (cancel /
  // stop). `runTranscription` captures this before awaiting and bails
  // if the value changed while it was waiting on the network.
  const transcriptionGenRef = useRef(0);

  // Streaming-speech bookkeeping for the current turn. `spokenLenRef`
  // is how many characters of the cleaned reply we've already queued;
  // `streamMsgIdRef` is the assistant message we're streaming;
  // `streamStartedRef` flips once we've entered the speaking phase.
  const spokenLenRef = useRef(0);
  const streamMsgIdRef = useRef<string | null>(null);
  const streamStartedRef = useRef(false);
  const resetStream = () => {
    spokenLenRef.current = 0;
    streamMsgIdRef.current = null;
    streamStartedRef.current = false;
  };

  const setError = useCallback((message: string) => {
    setErrorMessage(message);
    setPhase("error");
  }, []);

  useEffect(() => {
    let cancelled = false;
    getRuntimeSettings()
      .then((settings) => {
        const parsed = parseVadTimeoutMs(settings.vad_timeout_ms);
        if (!cancelled && parsed !== DEFAULT_VAD_TIMEOUT_MS) {
          setVadTimeoutMs(parsed);
        }
        const parsedSpeed = parseVoicePlaybackSpeed(settings.voice_playback_speed);
        if (!cancelled && parsedSpeed !== DEFAULT_VOICE_PLAYBACK_SPEED) {
          setVoicePlaybackSpeed(parsedSpeed);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const playback = useSpeechPlayback({
    playbackRate: voicePlaybackSpeed,
    onEnd: () => {
      // Fires once the whole streamed reply has finished speaking.
      if (!activeRef.current) return;
      resetStream();
      void recorderApi.current?.start();
      setPhase("listening");
    },
    onError: (err) => {
      // A single chunk failed to synthesise/play. Surface it but let
      // the queue keep draining — onEnd still restarts listening when
      // the rest of the reply finishes, so the loop never stalls.
      if (!activeRef.current) return;
      setErrorMessage(err.message);
    },
  });
  const playbackRef = useRef(playback);
  playbackRef.current = playback;

  const recorder = useVoiceRecorder({
    silenceDurationMs: vadTimeoutMs,
    onResult: ({ blob, durationMs }) => {
      if (!activeRef.current) return;
      if (durationMs < 400 || blob.size === 0) {
        // Effectively empty recording — restart listening.
        void recorderApi.current?.start();
        setPhase("listening");
        return;
      }
      void runTranscription(blob);
    },
    onError: (err) => {
      if (!activeRef.current) return;
      setError(err.message);
    },
    onUnavailable: (info) => {
      if (!activeRef.current) return;
      setMicUnavailable(info);
      setErrorMessage(info.message);
      setPhase("error");
    },
  });
  const recorderApi = useRef(recorder);
  recorderApi.current = recorder;

  const submitTranscript = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) {
        // Empty transcript — go back to listening.
        void recorderApi.current?.start();
        setPhase("listening");
        return;
      }
      // Snapshot the current message IDs so we can spot the new
      // assistant message that this submission produces.
      const snapshot = new Set<string>();
      try {
        const messages = aui.thread().getState().messages as unknown as AssistantMessageLike[];
        for (const m of messages) snapshot.add(m.id);
      } catch {
        /* If we can't snapshot, the next assistant message will still
         * trigger via isRunning settling. */
      }
      baselineIdsRef.current = snapshot;
      resetStream();
      try {
        aui.thread().composer().setText(trimmed);
        aui.thread().composer().send();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not send transcript.");
        return;
      }
      setPhase("thinking");
    },
    [aui, setError],
  );

  const runTranscription = useCallback(
    async (blob: Blob) => {
      const gen = ++transcriptionGenRef.current;
      setPhase("transcribing");
      try {
        const result = await transcribeAudio(blob);
        if (!activeRef.current || gen !== transcriptionGenRef.current) return;
        submitTranscript(result.text);
      } catch (e) {
        if (!activeRef.current || gen !== transcriptionGenRef.current) return;
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [setError, submitTranscript],
  );

  const restartListening = useCallback(() => {
    resetStream();
    void recorderApi.current?.start();
    setPhase("listening");
  }, []);

  // While the assistant is still generating, speak each sentence as it
  // completes. `streamText` re-renders this on every new token.
  useEffect(() => {
    if (!activeRef.current) return;
    if (!isRunning) return; // settle effect handles the final tail
    const ph = phaseRef.current;
    if (ph !== "thinking" && ph !== "speaking") return;
    if (playbackRef.current.status === "unavailable") return;
    let target: AssistantMessageLike | null = null;
    try {
      const messages = aui.thread().getState()
        .messages as unknown as AssistantMessageLike[];
      target = lastAssistantMessage(messages);
    } catch {
      return;
    }
    if (!target) return;
    // The last assistant message is still the previous reply — wait for
    // this turn's message to appear before speaking anything.
    if (
      streamMsgIdRef.current !== target.id &&
      baselineIdsRef.current.has(target.id)
    ) {
      return;
    }
    if (streamMsgIdRef.current !== target.id) {
      streamMsgIdRef.current = target.id;
      spokenLenRef.current = 0;
      streamStartedRef.current = false;
    }
    const raw = extractTextFromParts(target.parts);
    // Don't speak the inside of an unclosed ``` fence — wait for it to
    // close (or for the end-of-turn flush, which strips it anyway).
    if ((raw.match(/```/g)?.length ?? 0) % 2 === 1) return;
    const cleaned = cleanForSpeech(raw);
    if (cleaned.length < spokenLenRef.current) {
      // Cleaned text shrank (a late-closing fence reflowed earlier
      // prose). Resync the pointer rather than re-speaking.
      spokenLenRef.current = cleaned.length;
      return;
    }
    const { sentences, consumed } = takeSentences(
      cleaned.slice(spokenLenRef.current),
    );
    if (sentences.length === 0) return;
    for (const sentence of sentences) playbackRef.current.enqueue(sentence);
    spokenLenRef.current += consumed;
    if (!streamStartedRef.current) {
      streamStartedRef.current = true;
      setPhase("speaking");
    }
  }, [aui, isRunning, streamText]);

  // When the turn we initiated finishes, flush the trailing partial
  // sentence and signal end-of-speech so onEnd resumes listening.
  useEffect(() => {
    const wasRunning = wasRunningRef.current;
    wasRunningRef.current = isRunning;
    if (!activeRef.current) return;
    const ph = phaseRef.current;
    if (ph !== "thinking" && ph !== "speaking") return;
    if (!(wasRunning && !isRunning)) return;
    let target: AssistantMessageLike | null = null;
    try {
      const messages = aui.thread().getState()
        .messages as unknown as AssistantMessageLike[];
      target = lastAssistantMessage(messages);
    } catch {
      target = null;
    }
    if (!target) {
      restartListening();
      return;
    }
    if (playbackRef.current.status === "unavailable") {
      // No TTS — skip the speaking phase and listen again.
      lastSpokenIdRef.current = target.id;
      restartListening();
      return;
    }
    const cleaned = cleanForSpeech(extractTextFromParts(target.parts));
    const tail = cleaned.slice(spokenLenRef.current).trim();
    if (tail) playbackRef.current.enqueue(tail);
    lastSpokenIdRef.current = target.id;
    spokenLenRef.current = cleaned.length;
    streamMsgIdRef.current = null;
    if (!streamStartedRef.current && !tail) {
      // Nothing to say at all (e.g. a tool-only turn).
      restartListening();
      return;
    }
    setPhase("speaking");
    playbackRef.current.finish();
  }, [aui, isRunning, messageCount, restartListening]);

  const stop = useCallback(() => {
    setActive(false);
    setPhase("idle");
    setErrorMessage(null);
    setMicUnavailable(null);
    transcriptionGenRef.current += 1;
    resetStream();
    recorderApi.current?.cancel();
    playbackRef.current?.stop();
  }, []);

  const start = useCallback(() => {
    // Run the static check up front so the bar can show a coherent
    // reason without ever flashing through "Listening …".
    const issue = detectStaticMicAvailability();
    if (issue) {
      setActive(true);
      setMicUnavailable(issue);
      setErrorMessage(issue.message);
      setPhase("error");
      return;
    }
    setErrorMessage(null);
    setMicUnavailable(null);
    setActive(true);
    resetStream();
    setPhase("listening");
    void recorderApi.current?.start();
  }, []);

  const submitNow = useCallback(() => {
    recorderApi.current?.stop("manual");
  }, []);

  const cancelRecording = useCallback(() => {
    recorderApi.current?.cancel();
    transcriptionGenRef.current += 1;
    resetStream();
    if (!activeRef.current) return;
    // If the mic became unavailable mid-session, don't loop back into a
    // listening state we can't actually fulfill — leave the error
    // visible so the user can choose Type instead / Stop.
    if (micUnavailable) {
      setPhase("error");
      return;
    }
    void recorderApi.current?.start();
    setPhase("listening");
  }, [micUnavailable]);

  const stopSpeaking = useCallback(() => {
    playbackRef.current?.stop();
    resetStream();
    if (activeRef.current) {
      void recorderApi.current?.start();
      setPhase("listening");
    }
  }, []);

  const toggle = useCallback(() => {
    if (activeRef.current) stop();
    else start();
  }, [start, stop]);

  // Stop everything if the component unmounts mid-loop.
  useEffect(() => {
    return () => {
      recorderApi.current?.cancel();
      playbackRef.current?.stop();
    };
  }, []);

  return {
    status: {
      active,
      phase,
      errorMessage,
      ttsAvailable: playback.status !== "unavailable",
      // Either we already know statically (HTTP, no API) or we observed
      // a permission/device problem from the recorder.
      micUnavailable: micUnavailable ?? staticUnavailable,
    },
    start,
    stop,
    submitNow,
    cancelRecording,
    stopSpeaking,
    toggle,
  };
}
