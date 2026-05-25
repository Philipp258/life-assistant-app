import { useCallback, useEffect, useRef, useState } from "react";

import {
  getVadFactory,
  type VadDetector,
  type VadEvents,
} from "./vadDetector";

export type RecorderStatus =
  | "idle"
  | "starting"
  | "recording"
  | "stopping"
  | "error";

export type RecorderResult = {
  blob: Blob;
  durationMs: number;
};

/** How the active recording is detecting pauses. Surfaced for tests + the UI. */
export type SilenceDetectorMode = "vad" | "rms";

/**
 * Why the microphone can't be used. Distinguishes the cases the UI needs
 * to talk to the user about:
 * - `insecure-context`: page is on plain HTTP, browsers gate getUserMedia.
 * - `no-mediadevices`: browser has no `navigator.mediaDevices.getUserMedia`.
 * - `no-recorder`: `MediaRecorder` itself is missing.
 * - `no-audiocontext`: Web Audio API missing (no silence detection).
 * - `permission-denied`: user (or policy) denied mic access.
 * - `no-device`: no microphone hardware was found.
 * - `in-use`: another app is holding the mic exclusively.
 */
export type MicUnavailableKind =
  | "insecure-context"
  | "no-mediadevices"
  | "no-recorder"
  | "no-audiocontext"
  | "permission-denied"
  | "no-device"
  | "in-use";

export type MicUnavailable = {
  kind: MicUnavailableKind;
  message: string;
  /** True when the issue is structural — retrying without user action won't help. */
  fatal: boolean;
};

/**
 * Static (non-permission) availability check. Runs synchronously based
 * on what's exposed on `window` / `navigator`, so the UI can decide up
 * front whether voice mode can possibly work in this context.
 *
 * Permission denial / missing hardware can only be detected when
 * `getUserMedia` is actually invoked — those map to `permission-denied`
 * / `no-device` and are returned from `start()` via `onError` instead.
 */
export function detectStaticMicAvailability(): MicUnavailable | null {
  if (typeof window === "undefined" || typeof navigator === "undefined") {
    return {
      kind: "no-mediadevices",
      message: "Voice mode isn't available in this environment.",
      fatal: true,
    };
  }
  // `isSecureContext` is false on plain http://, except localhost. Browsers
  // strip `navigator.mediaDevices` in that case anyway, but checking it
  // explicitly lets us tell the user *why* the mic API is missing.
  if (window.isSecureContext === false) {
    return {
      kind: "insecure-context",
      message:
        "Voice mode requires HTTPS. Reload this page over https:// (or use localhost) to enable the microphone.",
      fatal: true,
    };
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return {
      kind: "no-mediadevices",
      message:
        "This browser doesn't expose the microphone API. Try a recent Chrome, Edge, Firefox, or Safari.",
      fatal: true,
    };
  }
  if (typeof window.MediaRecorder === "undefined") {
    return {
      kind: "no-recorder",
      message:
        "This browser can't record audio (MediaRecorder is missing). Try a recent Chrome, Edge, Firefox, or Safari.",
      fatal: true,
    };
  }
  const AudioCtx =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: typeof AudioContext })
      .webkitAudioContext;
  if (!AudioCtx) {
    return {
      kind: "no-audiocontext",
      message: "This browser doesn't support the Web Audio API needed for voice mode.",
      fatal: true,
    };
  }
  return null;
}

/**
 * Map a `getUserMedia` rejection into the typed unavailability shape so
 * the UI can render a sensible message. Names come from the WebRTC spec.
 *
 * `DOMException` doesn't necessarily extend `Error` in every runtime, so
 * pull `name`/`message` off the raw value before any `instanceof` cast
 * would coerce it to a generic `Error`.
 */
export function classifyGetUserMediaError(e: unknown): MicUnavailable {
  const raw = e as { name?: unknown; message?: unknown } | null | undefined;
  const name = typeof raw?.name === "string" ? raw.name : "";
  const message =
    typeof raw?.message === "string" && raw.message.length > 0
      ? raw.message
      : String(e);
  if (name === "NotAllowedError" || name === "SecurityError") {
    return {
      kind: "permission-denied",
      message:
        "Microphone access was blocked. Allow microphone access for this site in your browser settings, then try again.",
      fatal: false,
    };
  }
  if (name === "NotFoundError" || name === "OverconstrainedError") {
    return {
      kind: "no-device",
      message: "No microphone was found. Plug in or enable a microphone, then try again.",
      fatal: false,
    };
  }
  if (name === "NotReadableError" || name === "AbortError") {
    return {
      kind: "in-use",
      message:
        "The microphone is in use by another application. Close it and try again.",
      fatal: false,
    };
  }
  return {
    kind: "no-mediadevices",
    message: message || "The microphone couldn't be opened.",
    fatal: false,
  };
}

export type UseVoiceRecorderOptions = {
  /** RMS volume threshold (0..1) below which audio is considered silence in the fallback path. */
  silenceThreshold?: number;
  /** Sustained-silence duration that triggers an auto-submit. */
  silenceDurationMs?: number;
  /** Minimum recording duration before silence detection kicks in. */
  minRecordingMs?: number;
  /** Callback fired when recording auto-submits or the caller stops it. */
  onResult?: (result: RecorderResult) => void;
  /** Callback fired when the recorder errors out. */
  onError?: (error: Error) => void;
  /**
   * Callback fired when the mic can't be opened, with the reason
   * categorized so the UI can talk to the user about it (HTTPS,
   * permission, no device, …). When provided, this is preferred over
   * `onError` for mic-availability problems.
   */
  onUnavailable?: (info: MicUnavailable) => void;
  /** Test-only hook: receives the silence-detector mode picked at start time. */
  onDetectorReady?: (mode: SilenceDetectorMode) => void;
};

const DEFAULT_OPTIONS: Required<
  Omit<
    UseVoiceRecorderOptions,
    "onResult" | "onError" | "onUnavailable" | "onDetectorReady"
  >
> = {
  silenceThreshold: 0.015,
  silenceDurationMs: 4_000,
  minRecordingMs: 800,
};

type Active = {
  stream: MediaStream;
  recorder: MediaRecorder;
  audioCtx: AudioContext;
  analyser: AnalyserNode;
  source: MediaStreamAudioSourceNode;
  data: Float32Array;
  startedAt: number;
  rafId: number | null;
  /** When the most recent silence window started, or null while speaking. */
  silenceStart: number | null;
  /** True once we've detected at least one speech segment (VAD path only). */
  hasSpoken: boolean;
  /** Live speech state from VAD; ignored on the RMS fallback path. */
  isSpeaking: boolean;
  /** Active VAD instance — null when running on RMS fallback. */
  vad: VadDetector | null;
  mode: SilenceDetectorMode;
  chunks: Blob[];
  mimeType: string;
  /** Reason for the current stop transition: silence vs. manual vs. cancel. */
  stopReason: "silence" | "manual" | "cancel" | null;
  resolved: boolean;
};

/**
 * Records mic audio with `MediaRecorder` and watches the input for
 * pauses. Speech detection prefers a local browser VAD (Silero via
 * `@ricky0123/vad-web`); if that fails to load — old browser, missing
 * AudioWorklet, blocked WASM, etc. — it transparently falls back to a
 * fixed RMS threshold so voice mode still works.
 *
 * Either way the auto-submit rule is the same: after a sustained
 * silence window (`silenceDurationMs`), the recorder stops and emits a
 * `RecorderResult`. The recorder doesn't decide what to do with that
 * result — the caller (`useVoiceMode`) submits it through the chat
 * runtime.
 */
export function useVoiceRecorder(opts: UseVoiceRecorderOptions = {}) {
  const settings = { ...DEFAULT_OPTIONS, ...opts };
  const optsRef = useRef(opts);
  optsRef.current = opts;

  const [status, setStatus] = useState<RecorderStatus>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const activeRef = useRef<Active | null>(null);

  const cleanup = useCallback((active: Active) => {
    if (active.rafId !== null && typeof cancelAnimationFrame !== "undefined") {
      cancelAnimationFrame(active.rafId);
    }
    if (active.vad) {
      // VAD owns its AudioWorklet wiring on top of our shared stream.
      // Fire-and-forget the async destroy so cleanup stays synchronous —
      // the late promise rejection (if any) is harmless.
      void active.vad.destroy();
      active.vad = null;
    }
    try {
      active.source.disconnect();
    } catch {
      /* noop */
    }
    try {
      void active.audioCtx.close();
    } catch {
      /* noop */
    }
    for (const track of active.stream.getTracks()) {
      try {
        track.stop();
      } catch {
        /* noop */
      }
    }
  }, []);

  const finalize = useCallback(
    (active: Active, reason: Active["stopReason"]) => {
      if (active.resolved) return;
      active.resolved = true;
      cleanup(active);
      activeRef.current = null;

      if (reason === "cancel") {
        setStatus("idle");
        return;
      }

      const blob = new Blob(active.chunks, { type: active.mimeType });
      const durationMs = Math.max(0, performance.now() - active.startedAt);
      setStatus("idle");
      optsRef.current.onResult?.({ blob, durationMs });
    },
    [cleanup],
  );

  const stop = useCallback(
    (reason: "manual" | "cancel" = "manual") => {
      const active = activeRef.current;
      if (!active) return;
      active.stopReason = reason;
      setStatus("stopping");
      try {
        if (active.recorder.state !== "inactive") {
          active.recorder.stop();
          return;
        }
      } catch {
        /* fall through to manual finalize */
      }
      finalize(active, reason);
    },
    [finalize],
  );

  const reportUnavailable = useCallback((info: MicUnavailable) => {
    setStatus("error");
    setErrorMessage(info.message);
    if (optsRef.current.onUnavailable) {
      optsRef.current.onUnavailable(info);
    } else {
      optsRef.current.onError?.(new Error(info.message));
    }
  }, []);

  const start = useCallback(async () => {
    if (activeRef.current) return;
    setStatus("starting");
    setErrorMessage(null);

    const staticIssue = detectStaticMicAvailability();
    if (staticIssue) {
      reportUnavailable(staticIssue);
      return;
    }

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      reportUnavailable(classifyGetUserMediaError(e));
      return;
    }

    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(stream);
    } catch (e) {
      for (const t of stream.getTracks()) t.stop();
      const err = e instanceof Error ? e : new Error(String(e));
      setStatus("error");
      setErrorMessage(err.message);
      optsRef.current.onError?.(err);
      return;
    }

    const AudioCtx =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;

    const audioCtx = new AudioCtx();
    const source = audioCtx.createMediaStreamSource(stream);
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 1024;
    source.connect(analyser);
    const data = new Float32Array(analyser.fftSize);

    const active: Active = {
      stream,
      recorder,
      audioCtx,
      analyser,
      source,
      data,
      startedAt: performance.now(),
      rafId: null,
      silenceStart: null,
      hasSpoken: false,
      isSpeaking: false,
      vad: null,
      mode: "rms",
      chunks: [],
      mimeType: recorder.mimeType || "audio/webm",
      stopReason: null,
      resolved: false,
    };
    activeRef.current = active;

    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) active.chunks.push(event.data);
    };
    recorder.onerror = (event) => {
      const errorEvt = event as unknown as { error?: { message?: string } };
      const message = errorEvt.error?.message ?? "Recorder error";
      const err = new Error(message);
      setStatus("error");
      setErrorMessage(message);
      cleanup(active);
      activeRef.current = null;
      optsRef.current.onError?.(err);
    };
    recorder.onstop = () => {
      finalize(active, active.stopReason ?? "manual");
    };

    // Try the local Silero VAD first. If anything in the loader chain
    // fails (no AudioWorklet, blocked WASM, missing assets, …), fall
    // back to RMS so the user still gets a working voice loop.
    const vadEvents: VadEvents = {
      onSpeechStart: () => {
        if (active.resolved) return;
        active.isSpeaking = true;
        active.hasSpoken = true;
        active.silenceStart = null;
      },
      onSpeechEnd: () => {
        if (active.resolved) return;
        active.isSpeaking = false;
        active.silenceStart = performance.now();
      },
    };

    try {
      const factory = await getVadFactory();
      if (factory && !active.resolved) {
        const detector = await factory(stream, vadEvents);
        if (detector && !active.resolved) {
          active.vad = detector;
          active.mode = "vad";
        } else if (detector) {
          // Recorder was torn down while we were loading — destroy the
          // newly-built detector so we don't leak its worklet/context.
          void detector.destroy();
        }
      }
    } catch {
      /* VAD load/init failed — RMS fallback is already the default. */
    }

    if (active.resolved) return;
    optsRef.current.onDetectorReady?.(active.mode);

    const tickRms = () => {
      analyser.getFloatTimeDomainData(data);
      let sumSquares = 0;
      for (let i = 0; i < data.length; i += 1) {
        const v = data[i];
        sumSquares += v * v;
      }
      const rms = Math.sqrt(sumSquares / data.length);
      const elapsed = performance.now() - active.startedAt;

      if (elapsed < settings.minRecordingMs) return;

      if (rms < settings.silenceThreshold) {
        if (active.silenceStart === null) {
          active.silenceStart = performance.now();
        }
      } else {
        active.silenceStart = null;
      }
    };

    const tick = () => {
      if (active.resolved) return;

      if (active.mode === "rms") {
        tickRms();
      }

      const elapsed = performance.now() - active.startedAt;
      if (
        elapsed >= settings.minRecordingMs &&
        active.silenceStart !== null &&
        // VAD path: only auto-submit once we've actually heard speech,
        // so we don't ship empty audio when the user opens voice mode
        // and stays silent. RMS has no equivalent gate (it never knew
        // whether the user spoke), so we keep the historical behavior
        // there.
        (active.mode === "rms" || active.hasSpoken) &&
        performance.now() - active.silenceStart >= settings.silenceDurationMs
      ) {
        active.stopReason = "silence";
        try {
          if (active.recorder.state !== "inactive") {
            active.recorder.stop();
            return;
          }
        } catch {
          /* noop */
        }
        finalize(active, "silence");
        return;
      }

      active.rafId = requestAnimationFrame(tick);
    };

    try {
      recorder.start(250);
    } catch (e) {
      const err = e instanceof Error ? e : new Error(String(e));
      cleanup(active);
      activeRef.current = null;
      setStatus("error");
      setErrorMessage(err.message);
      optsRef.current.onError?.(err);
      return;
    }
    active.rafId = requestAnimationFrame(tick);
    setStatus("recording");
  }, [
    cleanup,
    finalize,
    reportUnavailable,
    settings.minRecordingMs,
    settings.silenceDurationMs,
    settings.silenceThreshold,
  ]);

  // Synchronously finalize so a follow-up `start()` (which guards on
  // `activeRef.current`) sees the slot as free. The browser still fires
  // `onstop` on a later microtask, but `finalize` is a no-op once
  // `resolved` is set, so the late event is harmless.
  const cancel = useCallback(() => {
    const active = activeRef.current;
    if (!active) return;
    active.stopReason = "cancel";
    active.resolved = true;
    try {
      if (active.recorder.state !== "inactive") active.recorder.stop();
    } catch {
      /* noop */
    }
    cleanup(active);
    activeRef.current = null;
    setStatus("idle");
  }, [cleanup]);

  useEffect(() => {
    return () => {
      const active = activeRef.current;
      if (active) {
        active.resolved = true;
        cleanup(active);
        activeRef.current = null;
      }
    };
  }, [cleanup]);

  return {
    status,
    errorMessage,
    start,
    stop,
    cancel,
  };
}
