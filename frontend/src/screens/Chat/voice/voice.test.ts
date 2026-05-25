import {
  act,
  cleanup,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./voiceApi", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  // Keep the real helpers (inferAudioFilename, transcribeAudio); only
  // stub the network TTS call so playback uses the browser fallback.
  return { ...actual, synthesizeSpeech: vi.fn() };
});

vi.mock("@assistant-ui/react", () => {
  const fakeThread = {
    getState: () => ({ messages: [], isRunning: false }),
    composer: () => ({ setText: vi.fn(), send: vi.fn() }),
  };
  return {
    useAui: () => ({ thread: () => fakeThread }),
    useAuiState: <T,>(selector: (s: unknown) => T): T =>
      selector({ thread: { isRunning: false, messages: [] } }),
  };
});

import { cleanForSpeech, useSpeechPlayback } from "./useSpeechPlayback";
import {
  DEFAULT_VOICE_PLAYBACK_SPEED,
  parseVoicePlaybackSpeed,
} from "../../Agent/runtimeSettingsApi";
import { takeSentences, useVoiceMode } from "./useVoiceMode";
import { VoiceModeBar } from "./VoiceModeBar";
import {
  classifyGetUserMediaError,
  detectStaticMicAvailability,
  type SilenceDetectorMode,
  useVoiceRecorder,
} from "./useVoiceRecorder";
import {
  __setVadFactoryForTests,
  type VadDetector,
  type VadEvents,
  type VadFactory,
} from "./vadDetector";
import { inferAudioFilename, synthesizeSpeech } from "./voiceApi";

describe("inferAudioFilename", () => {
  it.each([
    ["audio/webm", "clip.webm"],
    ["audio/webm;codecs=opus", "clip.webm"],
    ["audio/mp4", "clip.mp4"],
    ["audio/x-m4a", "clip.mp4"],
    ["audio/mpeg", "clip.mp3"],
    ["audio/wav", "clip.wav"],
    ["audio/ogg", "clip.ogg"],
    [undefined, "clip.webm"],
    ["", "clip.webm"],
    ["application/octet-stream", "clip.webm"],
  ])("maps %s to %s", (mime, expected) => {
    expect(inferAudioFilename(mime)).toBe(expected);
  });
});

describe("cleanForSpeech", () => {
  it("strips inline code markers but keeps the contents", () => {
    expect(cleanForSpeech("call `foo()` to start")).toBe("call foo() to start");
  });

  it("collapses bold and italic markers", () => {
    expect(cleanForSpeech("**hi** _there_")).toBe("hi there");
  });

  it("removes heading markers", () => {
    expect(cleanForSpeech("# Big\n## small\nbody")).toBe("Big\nsmall\nbody");
  });

  it("turns markdown links into their visible text", () => {
    expect(cleanForSpeech("see [docs](https://example.com)")).toBe("see docs");
  });

  it("strips code fences but keeps the content lines", () => {
    const input = "before\n```ts\nconst x = 1;\n```\nafter";
    expect(cleanForSpeech(input)).toContain("const x = 1;");
    expect(cleanForSpeech(input)).not.toContain("```");
  });

  it("strips bullets and ordered list markers", () => {
    expect(cleanForSpeech("- one\n- two\n1. three")).toBe("one\ntwo\nthree");
  });

  it("collapses extra blank lines", () => {
    expect(cleanForSpeech("a\n\n\n\nb")).toBe("a\n\nb");
  });
});

describe("parseVoicePlaybackSpeed", () => {
  it("defaults missing and invalid values", () => {
    expect(parseVoicePlaybackSpeed("")).toBe(DEFAULT_VOICE_PLAYBACK_SPEED);
    expect(parseVoicePlaybackSpeed("fast")).toBe(DEFAULT_VOICE_PLAYBACK_SPEED);
  });

  it("clamps values to the supported speech rate range", () => {
    expect(parseVoicePlaybackSpeed("0.25")).toBe(0.5);
    expect(parseVoicePlaybackSpeed("2.5")).toBe(2);
  });
});

type WindowOverrides = {
  isSecureContext?: boolean;
  hasMediaDevices?: boolean;
  hasMediaRecorder?: boolean;
  hasAudioContext?: boolean;
};

function stubBrowser(overrides: WindowOverrides = {}) {
  const {
    isSecureContext = true,
    hasMediaDevices = true,
    hasMediaRecorder = true,
    hasAudioContext = true,
  } = overrides;

  Object.defineProperty(window, "isSecureContext", {
    configurable: true,
    value: isSecureContext,
  });

  if (hasMediaDevices) {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [],
        }),
      },
    });
  } else {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: undefined,
    });
  }

  if (hasMediaRecorder) {
    (window as unknown as { MediaRecorder: unknown }).MediaRecorder =
      function FakeMediaRecorder() {
        return { start: vi.fn(), stop: vi.fn(), state: "inactive" };
      };
  } else {
    (window as unknown as { MediaRecorder: unknown }).MediaRecorder = undefined;
  }

  if (hasAudioContext) {
    (window as unknown as { AudioContext: unknown }).AudioContext = function () {
      return {
        createMediaStreamSource: () => ({ connect: () => undefined, disconnect: () => undefined }),
        createAnalyser: () => ({ fftSize: 0, getFloatTimeDomainData: () => undefined }),
        close: () => undefined,
      };
    };
  } else {
    (window as unknown as { AudioContext: unknown }).AudioContext = undefined;
    (window as unknown as { webkitAudioContext: unknown }).webkitAudioContext =
      undefined;
  }
}

describe("detectStaticMicAvailability", () => {
  beforeEach(() => stubBrowser());
  afterEach(() => vi.restoreAllMocks());

  it("returns null when everything is present and the context is secure", () => {
    expect(detectStaticMicAvailability()).toBeNull();
  });

  it("flags an insecure context with an HTTPS-specific message", () => {
    stubBrowser({ isSecureContext: false });
    const result = detectStaticMicAvailability();
    expect(result?.kind).toBe("insecure-context");
    expect(result?.fatal).toBe(true);
    expect(result?.message).toMatch(/https/i);
  });

  it("flags a missing mediaDevices API distinctly from insecure context", () => {
    stubBrowser({ hasMediaDevices: false });
    const result = detectStaticMicAvailability();
    expect(result?.kind).toBe("no-mediadevices");
    expect(result?.fatal).toBe(true);
    expect(result?.message).not.toMatch(/https/i);
  });

  it("flags missing MediaRecorder", () => {
    stubBrowser({ hasMediaRecorder: false });
    expect(detectStaticMicAvailability()?.kind).toBe("no-recorder");
  });

  it("flags missing Web Audio API", () => {
    stubBrowser({ hasAudioContext: false });
    expect(detectStaticMicAvailability()?.kind).toBe("no-audiocontext");
  });
});

describe("classifyGetUserMediaError", () => {
  it("maps NotAllowedError to permission-denied", () => {
    const err = new DOMException("denied", "NotAllowedError");
    const info = classifyGetUserMediaError(err);
    expect(info.kind).toBe("permission-denied");
    expect(info.fatal).toBe(false);
    expect(info.message).toMatch(/permission|allow/i);
  });

  it("maps NotFoundError to no-device", () => {
    const err = new DOMException("none", "NotFoundError");
    expect(classifyGetUserMediaError(err).kind).toBe("no-device");
  });

  it("maps NotReadableError to in-use", () => {
    const err = new DOMException("busy", "NotReadableError");
    expect(classifyGetUserMediaError(err).kind).toBe("in-use");
  });

  it("falls back to no-mediadevices for unknown errors", () => {
    expect(classifyGetUserMediaError(new Error("?")).kind).toBe(
      "no-mediadevices",
    );
  });
});

describe("useVoiceRecorder.start mic unavailability", () => {
  beforeEach(() => stubBrowser());
  afterEach(() => vi.restoreAllMocks());

  it("reports insecure-context via onUnavailable, not as a generic onError", async () => {
    stubBrowser({ isSecureContext: false });
    const onUnavailable = vi.fn();
    const onError = vi.fn();
    const { result } = renderHook(() =>
      useVoiceRecorder({ onUnavailable, onError }),
    );

    await act(async () => {
      await result.current.start();
    });

    expect(onUnavailable).toHaveBeenCalledTimes(1);
    expect(onUnavailable.mock.calls[0][0].kind).toBe("insecure-context");
    expect(onError).not.toHaveBeenCalled();
    expect(result.current.errorMessage).toMatch(/https/i);
    expect(result.current.status).toBe("error");
  });

  it("reports missing mediaDevices via onUnavailable with no-mediadevices kind", async () => {
    stubBrowser({ hasMediaDevices: false });
    const onUnavailable = vi.fn();
    const { result } = renderHook(() => useVoiceRecorder({ onUnavailable }));

    await act(async () => {
      await result.current.start();
    });

    expect(onUnavailable).toHaveBeenCalledTimes(1);
    expect(onUnavailable.mock.calls[0][0].kind).toBe("no-mediadevices");
  });

  it("reports a denied permission via onUnavailable (permission-denied)", async () => {
    stubBrowser();
    const denied = new DOMException("denied", "NotAllowedError");
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockRejectedValue(denied) },
    });
    const onUnavailable = vi.fn();
    const { result } = renderHook(() => useVoiceRecorder({ onUnavailable }));

    await act(async () => {
      await result.current.start();
    });

    expect(onUnavailable).toHaveBeenCalledTimes(1);
    expect(onUnavailable.mock.calls[0][0].kind).toBe("permission-denied");
  });

  it("falls back to onError when onUnavailable is not provided", async () => {
    stubBrowser({ isSecureContext: false });
    const onError = vi.fn();
    const { result } = renderHook(() => useVoiceRecorder({ onError }));

    await act(async () => {
      await result.current.start();
    });

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0].message).toMatch(/https/i);
  });
});

describe("useVoiceRecorder.cancel", () => {
  beforeEach(() => stubBrowser());
  afterEach(() => vi.restoreAllMocks());

  it("does not invoke onError or onUnavailable when called from idle", () => {
    const onError = vi.fn();
    const onUnavailable = vi.fn();
    const { result } = renderHook(() =>
      useVoiceRecorder({ onError, onUnavailable }),
    );

    act(() => {
      result.current.cancel();
    });

    expect(onError).not.toHaveBeenCalled();
    expect(onUnavailable).not.toHaveBeenCalled();
    expect(result.current.errorMessage).toBeNull();
    expect(result.current.status).toBe("idle");
  });

  it("clears the error state after a failed start when stop() is called", async () => {
    stubBrowser({ isSecureContext: false });
    const { result } = renderHook(() => useVoiceRecorder({}));

    await act(async () => {
      await result.current.start();
    });
    expect(result.current.status).toBe("error");

    // stop() on an idle (non-active) recorder is a no-op and must not
    // re-surface the prior unavailability message — that's the
    // "Microphone is not available as a cancel error" regression.
    act(() => {
      result.current.stop("cancel");
    });
    // After stop on an inactive recorder, status stays at "error"
    // (nothing to stop) and the existing error message is unchanged —
    // but no *new* error fires. Callers (useVoiceMode.stop) own the
    // higher-level reset of the displayed error.
    expect(result.current.status).toBe("error");
  });
});

describe("useVoiceMode mic availability surface", () => {
  beforeEach(() => stubBrowser());
  afterEach(() => vi.restoreAllMocks());

  it("on insecure context, start() surfaces an HTTPS-specific error and skips the recorder", async () => {
    stubBrowser({ isSecureContext: false });
    const { result } = renderHook(() => useVoiceMode());

    act(() => {
      result.current.start();
    });

    expect(result.current.status.active).toBe(true);
    expect(result.current.status.phase).toBe("error");
    expect(result.current.status.micUnavailable?.kind).toBe("insecure-context");
    expect(result.current.status.errorMessage).toMatch(/https/i);
  });

  it("on missing mediaDevices, start() flags no-mediadevices instead of a generic 'not available' message", async () => {
    stubBrowser({ hasMediaDevices: false });
    const { result } = renderHook(() => useVoiceMode());

    act(() => {
      result.current.start();
    });

    expect(result.current.status.phase).toBe("error");
    expect(result.current.status.micUnavailable?.kind).toBe("no-mediadevices");
  });

  it("stop() clears micUnavailable and errorMessage and exits voice mode cleanly", async () => {
    stubBrowser({ isSecureContext: false });
    const { result } = renderHook(() => useVoiceMode());

    act(() => {
      result.current.start();
    });
    expect(result.current.status.active).toBe(true);
    expect(result.current.status.errorMessage).not.toBeNull();

    act(() => {
      result.current.stop();
    });

    // "Type instead" / "Stop" both call stop() — the bar is hidden via
    // active=false, and the error doesn't linger as a "cancel error".
    expect(result.current.status.active).toBe(false);
    expect(result.current.status.errorMessage).toBeNull();
    expect(result.current.status.micUnavailable?.kind).toBe("insecure-context");
    // Note: micUnavailable from the static check is still surfaced so a
    // re-toggle can show the same reason — but with active=false the
    // bar isn't rendered, so the user sees a clean exit.
  });

  it("cancelRecording() does not surface a stale 'mic unavailable' error mid-listening", async () => {
    // Mic is fully available — start() succeeds, then cancelRecording()
    // should *not* fire any unavailability error.
    stubBrowser();
    const { result } = renderHook(() => useVoiceMode());

    await act(async () => {
      result.current.start();
    });

    await act(async () => {
      result.current.cancelRecording();
    });

    expect(result.current.status.errorMessage).toBeNull();
    expect(result.current.status.phase).toBe("listening");
  });
});

// ---------------------------------------------------------------------------
// VAD-driven silence detection (and RMS fallback)
// ---------------------------------------------------------------------------

type FakeRecorder = {
  state: "inactive" | "recording";
  mimeType: string;
  start: ReturnType<typeof vi.fn>;
  stop: ReturnType<typeof vi.fn>;
  ondataavailable: ((ev: { data: Blob }) => void) | null;
  onstop: (() => void) | null;
  onerror: ((ev: unknown) => void) | null;
};

type RecordingHarness = {
  recorder: FakeRecorder;
  flushFrame: () => void;
  advance: (ms: number) => void;
};

function installRecordingHarness(): RecordingHarness {
  // Fake clock — both `performance.now()` and our advance helper read
  // from the same value so RAF ticks see consistent timing.
  let now = 1000;
  vi.spyOn(performance, "now").mockImplementation(() => now);

  // Synchronous RAF queue. Each `flushFrame` runs whatever callbacks
  // are waiting. The recorder loop re-queues itself, so we re-run
  // until the active recording resolves (or we hit a sane cap).
  const queue: FrameRequestCallback[] = [];
  vi.spyOn(window, "requestAnimationFrame").mockImplementation(
    (cb: FrameRequestCallback) => {
      queue.push(cb);
      return queue.length;
    },
  );
  vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {
    /* harmless: tick checks `active.resolved` and bails. */
  });

  const recorder: FakeRecorder = {
    state: "inactive",
    mimeType: "audio/webm",
    start: vi.fn(function start(this: FakeRecorder) {
      this.state = "recording";
    }),
    stop: vi.fn(function stop(this: FakeRecorder) {
      if (this.state === "inactive") return;
      this.state = "inactive";
      // Mirror the browser: `onstop` fires on a microtask after stop().
      queueMicrotask(() => {
        this.onstop?.();
      });
    }),
    ondataavailable: null,
    onstop: null,
    onerror: null,
  };
  // Bind the function context so `this` is always our recorder.
  recorder.start = vi.fn(() => {
    recorder.state = "recording";
  });
  recorder.stop = vi.fn(() => {
    if (recorder.state === "inactive") return;
    recorder.state = "inactive";
    queueMicrotask(() => {
      recorder.onstop?.();
    });
  });

  (window as unknown as { MediaRecorder: unknown }).MediaRecorder =
    function FakeMediaRecorder() {
      return recorder;
    };

  Object.defineProperty(window, "isSecureContext", {
    configurable: true,
    value: true,
  });
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi.fn().mockResolvedValue({
        getTracks: () => [{ stop: vi.fn() }],
      }),
    },
  });

  (window as unknown as { AudioContext: unknown }).AudioContext = function () {
    return {
      createMediaStreamSource: () => ({
        connect: () => undefined,
        disconnect: () => undefined,
      }),
      createAnalyser: () => ({
        fftSize: 0,
        getFloatTimeDomainData: () => undefined,
      }),
      close: () => undefined,
    };
  };

  return {
    recorder,
    advance: (ms: number) => {
      now += ms;
    },
    flushFrame: () => {
      const cb = queue.shift();
      if (cb) cb(now);
    },
  };
}

function makeFakeVadFactory(): {
  factory: VadFactory;
  destroy: ReturnType<typeof vi.fn>;
  events: { current: VadEvents | null };
  call: ReturnType<typeof vi.fn>;
} {
  const destroy = vi.fn(async () => undefined);
  const events: { current: VadEvents | null } = { current: null };
  const call = vi.fn();
  const factory: VadFactory = async (stream, ev) => {
    call(stream, ev);
    events.current = ev;
    const detector: VadDetector = { destroy };
    return detector;
  };
  return { factory, destroy, events, call };
}

describe("useVoiceRecorder VAD-driven silence detection", () => {
  let harness: RecordingHarness;

  beforeEach(() => {
    harness = installRecordingHarness();
  });

  afterEach(() => {
    __setVadFactoryForTests(undefined);
    vi.restoreAllMocks();
  });

  it("uses the VAD factory when one is available and reports vad mode", async () => {
    const { factory, call } = makeFakeVadFactory();
    __setVadFactoryForTests(factory);
    const onDetectorReady = vi.fn();

    const { result } = renderHook(() =>
      useVoiceRecorder({ onDetectorReady, silenceDurationMs: 300 }),
    );

    await act(async () => {
      await result.current.start();
    });

    expect(call).toHaveBeenCalledTimes(1);
    expect(onDetectorReady).toHaveBeenCalledWith(
      "vad" satisfies SilenceDetectorMode,
    );
  });

  it("auto-submits after VAD reports speech end and silenceDurationMs elapses", async () => {
    const { factory, events } = makeFakeVadFactory();
    __setVadFactoryForTests(factory);
    const onResult = vi.fn();

    const { result } = renderHook(() =>
      useVoiceRecorder({
        onResult,
        silenceDurationMs: 200,
        minRecordingMs: 100,
      }),
    );

    await act(async () => {
      await result.current.start();
    });

    // User speaks, then stops.
    act(() => {
      events.current?.onSpeechStart();
    });
    harness.advance(150);
    act(() => {
      events.current?.onSpeechEnd();
    });

    // Time hasn't passed enough yet — the next frame shouldn't trigger
    // an auto-submit.
    act(() => {
      harness.flushFrame();
    });
    expect(onResult).not.toHaveBeenCalled();
    expect(harness.recorder.state).toBe("recording");

    // Cross the silence threshold.
    harness.advance(250);
    act(() => {
      harness.flushFrame();
    });

    expect(harness.recorder.state).toBe("inactive");
    // `onstop` fires via microtask → onResult fires from finalize.
    await act(async () => {
      await Promise.resolve();
    });
    expect(onResult).toHaveBeenCalledTimes(1);
  });

  it("does not auto-submit when VAD never reports speech (avoids submitting silence)", async () => {
    const { factory } = makeFakeVadFactory();
    __setVadFactoryForTests(factory);
    const onResult = vi.fn();

    const { result } = renderHook(() =>
      useVoiceRecorder({
        onResult,
        silenceDurationMs: 200,
        minRecordingMs: 100,
      }),
    );

    await act(async () => {
      await result.current.start();
    });

    // Run several frames worth of "silence" without ever firing
    // onSpeechStart/End. The VAD path should NOT auto-submit because
    // hasSpoken is still false.
    for (let i = 0; i < 10; i += 1) {
      harness.advance(100);
      act(() => {
        harness.flushFrame();
      });
    }

    expect(onResult).not.toHaveBeenCalled();
    expect(harness.recorder.state).toBe("recording");
  });

  it("clears a pending silence window when speech resumes (no premature auto-submit)", async () => {
    const { factory, events } = makeFakeVadFactory();
    __setVadFactoryForTests(factory);
    const onResult = vi.fn();

    const { result } = renderHook(() =>
      useVoiceRecorder({
        onResult,
        silenceDurationMs: 200,
        minRecordingMs: 100,
      }),
    );

    await act(async () => {
      await result.current.start();
    });

    act(() => {
      events.current?.onSpeechStart();
    });
    harness.advance(120);
    act(() => {
      events.current?.onSpeechEnd();
    });

    // Mid-pause (before threshold) the user resumes speaking — silence
    // window must reset.
    harness.advance(150);
    act(() => {
      events.current?.onSpeechStart();
    });
    harness.advance(120);
    act(() => {
      events.current?.onSpeechEnd();
    });

    // Now advance just below the threshold from the latest speech-end:
    // 150ms. Auto-submit must NOT fire.
    harness.advance(150);
    act(() => {
      harness.flushFrame();
    });
    expect(onResult).not.toHaveBeenCalled();
    expect(harness.recorder.state).toBe("recording");

    // Cross the threshold from the *latest* speech-end.
    harness.advance(120);
    act(() => {
      harness.flushFrame();
    });
    expect(harness.recorder.state).toBe("inactive");
    await act(async () => {
      await Promise.resolve();
    });
    expect(onResult).toHaveBeenCalledTimes(1);
  });

  it("destroys the VAD detector on cancel()", async () => {
    const { factory, destroy } = makeFakeVadFactory();
    __setVadFactoryForTests(factory);

    const { result } = renderHook(() =>
      useVoiceRecorder({ silenceDurationMs: 200 }),
    );

    await act(async () => {
      await result.current.start();
    });
    expect(destroy).not.toHaveBeenCalled();

    act(() => {
      result.current.cancel();
    });

    expect(destroy).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe("idle");
  });

  it("destroys the VAD detector on auto-submit (silence stop)", async () => {
    const { factory, destroy, events } = makeFakeVadFactory();
    __setVadFactoryForTests(factory);
    const onResult = vi.fn();

    const { result } = renderHook(() =>
      useVoiceRecorder({
        onResult,
        silenceDurationMs: 100,
        minRecordingMs: 50,
      }),
    );

    await act(async () => {
      await result.current.start();
    });

    act(() => {
      events.current?.onSpeechStart();
    });
    harness.advance(80);
    act(() => {
      events.current?.onSpeechEnd();
    });
    harness.advance(150);
    act(() => {
      harness.flushFrame();
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(onResult).toHaveBeenCalledTimes(1);
    expect(destroy).toHaveBeenCalledTimes(1);
  });

  it("destroys the VAD detector on hook unmount", async () => {
    const { factory, destroy } = makeFakeVadFactory();
    __setVadFactoryForTests(factory);

    const { result, unmount } = renderHook(() => useVoiceRecorder({}));

    await act(async () => {
      await result.current.start();
    });

    unmount();
    expect(destroy).toHaveBeenCalledTimes(1);
  });
});

describe("useVoiceRecorder RMS fallback", () => {
  let harness: RecordingHarness;

  beforeEach(() => {
    harness = installRecordingHarness();
  });

  afterEach(() => {
    __setVadFactoryForTests(undefined);
    vi.restoreAllMocks();
  });

  it("falls back to RMS mode when no VAD factory is available", async () => {
    __setVadFactoryForTests(null);
    const onDetectorReady = vi.fn();

    const { result } = renderHook(() =>
      useVoiceRecorder({
        onDetectorReady,
        silenceDurationMs: 200,
        minRecordingMs: 50,
      }),
    );

    await act(async () => {
      await result.current.start();
    });

    expect(onDetectorReady).toHaveBeenCalledWith(
      "rms" satisfies SilenceDetectorMode,
    );
  });

  it("falls back to RMS when the VAD factory throws", async () => {
    const throwing: VadFactory = async () => {
      throw new Error("vad init failed");
    };
    __setVadFactoryForTests(throwing);
    const onDetectorReady = vi.fn();

    const { result } = renderHook(() =>
      useVoiceRecorder({
        onDetectorReady,
        silenceDurationMs: 200,
        minRecordingMs: 50,
      }),
    );

    await act(async () => {
      await result.current.start();
    });

    expect(onDetectorReady).toHaveBeenCalledWith("rms");
  });

  it("auto-submits via RMS detection after sustained low-level audio", async () => {
    __setVadFactoryForTests(null);
    const onResult = vi.fn();

    const { result } = renderHook(() =>
      useVoiceRecorder({
        onResult,
        silenceDurationMs: 200,
        minRecordingMs: 100,
      }),
    );

    await act(async () => {
      await result.current.start();
    });

    // Cross minRecordingMs so silence detection is allowed to engage.
    harness.advance(120);
    act(() => {
      harness.flushFrame();
    });
    // First post-min-recording tick records silenceStart but doesn't
    // trigger yet — the threshold is measured from that timestamp.
    expect(onResult).not.toHaveBeenCalled();

    // Advance past the silence window from the moment silenceStart was
    // recorded, then run a frame that crosses it.
    harness.advance(250);
    act(() => {
      harness.flushFrame();
    });

    expect(harness.recorder.state).toBe("inactive");
    await act(async () => {
      await Promise.resolve();
    });
    expect(onResult).toHaveBeenCalledTimes(1);
  });

  it("does not auto-submit before minRecordingMs has elapsed (RMS path)", async () => {
    __setVadFactoryForTests(null);
    const onResult = vi.fn();

    const { result } = renderHook(() =>
      useVoiceRecorder({
        onResult,
        silenceDurationMs: 100,
        minRecordingMs: 500,
      }),
    );

    await act(async () => {
      await result.current.start();
    });

    // 300ms total: still under the 500ms minimum. Many frames of
    // "silence" should not trigger.
    for (let i = 0; i < 5; i += 1) {
      harness.advance(60);
      act(() => {
        harness.flushFrame();
      });
    }

    expect(onResult).not.toHaveBeenCalled();
    expect(harness.recorder.state).toBe("recording");
  });
});

describe("takeSentences", () => {
  it("returns nothing for empty input", () => {
    expect(takeSentences("")).toEqual({ sentences: [], consumed: 0 });
  });

  it("does not emit a sentence until its terminator is followed by space", () => {
    // Still streaming — "Hello." could be mid-word ("Hello.com"); wait.
    expect(takeSentences("Hello.")).toEqual({ sentences: [], consumed: 0 });
  });

  it("emits a completed sentence and leaves the trailing partial", () => {
    const { sentences, consumed } = takeSentences("Hello there. And the");
    expect(sentences).toEqual(["Hello there."]);
    // Consumes through the boundary whitespace; "And the" stays.
    expect("Hello there. And the".slice(consumed)).toBe("And the");
  });

  it("splits multiple sentences across . ! ? and ellipsis", () => {
    expect(takeSentences("One. Two! Three? Wait… go").sentences).toEqual([
      "One.",
      "Two!",
      "Three?",
      "Wait…",
    ]);
  });

  it("treats a newline as a sentence boundary", () => {
    expect(takeSentences("Line one.\nLine two. x").sentences).toEqual([
      "Line one.",
      "Line two.",
    ]);
  });

  it("keeps a closing quote with the sentence it ends", () => {
    expect(takeSentences('He said "hi." Then left').sentences).toEqual([
      'He said "hi."',
    ]);
  });

  it("handles stacked terminators as one boundary", () => {
    expect(takeSentences("Really?! Yes").sentences).toEqual(["Really?!"]);
  });
});

describe("VoiceModeBar button surface", () => {
  afterEach(cleanup);

  const makeVoice = (
    phase: "listening" | "speaking" | "transcribing",
  ): ReturnType<typeof useVoiceMode> =>
    ({
      status: {
        active: true,
        phase,
        errorMessage: null,
        ttsAvailable: true,
        micUnavailable: null,
      },
      start: vi.fn(),
      stop: vi.fn(),
      submitNow: vi.fn(),
      cancelRecording: vi.fn(),
      stopSpeaking: vi.fn(),
      toggle: vi.fn(),
    }) as unknown as ReturnType<typeof useVoiceMode>;

  it("listening: only Submit now + a single Stop, no Cancel/Type instead", () => {
    render(createElement(VoiceModeBar, { voice: makeVoice("listening") }));
    expect(
      screen.getByRole("button", { name: /submit now/i }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: /stop voice mode/i })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /cancel/i })).toBeNull();
    expect(
      screen.queryByRole("button", { name: /type instead/i }),
    ).toBeNull();
    expect(screen.getAllByRole("button")).toHaveLength(2);
  });

  it("speaking: Stop speaking + a single Stop, nothing else", () => {
    render(createElement(VoiceModeBar, { voice: makeVoice("speaking") }));
    expect(
      screen.getByRole("button", { name: /stop speaking/i }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: /stop voice mode/i })).toBeTruthy();
    expect(screen.getAllByRole("button")).toHaveLength(2);
  });

  it("transcribing: no Cancel, just the single Stop", () => {
    render(createElement(VoiceModeBar, { voice: makeVoice("transcribing") }));
    expect(screen.queryByRole("button", { name: /cancel/i })).toBeNull();
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.getByRole("button", { name: /stop voice mode/i })).toBeTruthy();
  });
});

describe("useSpeechPlayback streaming queue", () => {
  let speakCalls: string[];
  let utteranceRates: number[];

  function installSynth() {
    vi.mocked(synthesizeSpeech).mockResolvedValue(null);
    speakCalls = [];
    utteranceRates = [];
    const synth = {
      speak: vi.fn((u: { text: string; rate: number; onend?: () => void }) => {
        speakCalls.push(u.text);
        utteranceRates.push(u.rate);
        setTimeout(() => u.onend?.(), 0);
      }),
      cancel: vi.fn(),
      getVoices: () => [],
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    };
    vi.stubGlobal("speechSynthesis", synth);
    vi.stubGlobal(
      "SpeechSynthesisUtterance",
      class {
        text: string;
        rate = 1;
        onend?: () => void;
        onerror?: (e: unknown) => void;
        constructor(t: string) {
          this.text = t;
        }
      },
    );
    return synth;
  }

  afterEach(() => {
    vi.unstubAllGlobals();
    cleanup();
  });

  it("speak() plays once and fires onEnd", async () => {
    installSynth();
    const onEnd = vi.fn();
    const { result } = renderHook(() => useSpeechPlayback({ onEnd }));

    act(() => {
      result.current.speak("Hello world.");
    });

    await waitFor(() => expect(onEnd).toHaveBeenCalledTimes(1));
    expect(speakCalls).toEqual(["Hello world."]);
    expect(utteranceRates).toEqual([DEFAULT_VOICE_PLAYBACK_SPEED]);
  });

  it("applies the configured speed to browser speech fallback", async () => {
    installSynth();
    const onEnd = vi.fn();
    const { result } = renderHook(() =>
      useSpeechPlayback({ onEnd, playbackRate: 1.35 }),
    );

    act(() => {
      result.current.speak("Hello world.");
    });

    await waitFor(() => expect(onEnd).toHaveBeenCalledTimes(1));
    expect(utteranceRates).toEqual([1.35]);
  });

  it("applies the configured speed to server audio playback", async () => {
    installSynth();
    vi.mocked(synthesizeSpeech).mockResolvedValue({
      audio: new Blob(["audio"], { type: "audio/mpeg" }),
      contentType: "audio/mpeg",
      provider: "openrouter",
      model: "canopylabs/orpheus-3b-0.1-ft",
    });
    const audioInstances: Array<{ playbackRate: number }> = [];
    vi.stubGlobal(
      "URL",
      class extends URL {
        static createObjectURL = vi.fn(() => "blob:test-audio");
        static revokeObjectURL = vi.fn();
      },
    );
    vi.stubGlobal(
      "Audio",
      class {
        playbackRate = 1;
        onended: (() => void) | null = null;
        onerror: (() => void) | null = null;
        constructor(_url: string) {
          audioInstances.push(this);
        }
        play() {
          setTimeout(() => this.onended?.(), 0);
          return Promise.resolve();
        }
        pause() {}
        removeAttribute(_name: string) {}
        load() {}
      },
    );
    const onEnd = vi.fn();
    const { result } = renderHook(() =>
      useSpeechPlayback({ onEnd, playbackRate: 1.2 }),
    );

    act(() => {
      result.current.speak("Hello world.");
    });

    await waitFor(() => expect(onEnd).toHaveBeenCalledTimes(1));
    expect(audioInstances[0]?.playbackRate).toBe(1.2);
    expect(speakCalls).toEqual([]);
  });

  it("plays enqueued chunks in order and fires onEnd once after finish()", async () => {
    installSynth();
    const onEnd = vi.fn();
    const { result } = renderHook(() => useSpeechPlayback({ onEnd }));

    act(() => {
      result.current.enqueue("First one.");
      result.current.enqueue("Second two.");
      result.current.finish();
    });

    await waitFor(() => expect(onEnd).toHaveBeenCalledTimes(1));
    expect(speakCalls).toEqual(["First one.", "Second two."]);
  });

  it("stop() before finish() interrupts and never fires onEnd", async () => {
    const synth = installSynth();
    const onEnd = vi.fn();
    const { result } = renderHook(() => useSpeechPlayback({ onEnd }));

    act(() => {
      result.current.enqueue("Only one.");
      result.current.stop();
    });

    await new Promise((r) => setTimeout(r, 20));
    expect(onEnd).not.toHaveBeenCalled();
    expect(synth.cancel).toHaveBeenCalled();
  });
});
