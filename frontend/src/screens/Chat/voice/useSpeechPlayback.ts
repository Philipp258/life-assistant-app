import { useCallback, useEffect, useRef, useState } from "react";

import { parseVoicePlaybackSpeed } from "../../Agent/runtimeSettingsApi";
import { synthesizeSpeech } from "./voiceApi";

export type SpeechStatus = "idle" | "speaking" | "unavailable";

export type SpeechPlaybackOptions = {
  onEnd?: () => void;
  onError?: (error: Error) => void;
  playbackRate?: number;
};

/**
 * Strip markdown noise that the browser TTS would otherwise speak
 * literally (asterisks, backticks, hashes, link syntax). The output is
 * plain prose suitable for SpeechSynthesisUtterance.
 */
export function cleanForSpeech(input: string): string {
  return input
    // Code fences and inline code: keep the contents, drop the markers.
    .replace(/```[\s\S]*?```/g, (m) => m.replace(/```[a-zA-Z0-9]*\n?/g, "").replace(/```/g, ""))
    .replace(/`([^`]+)`/g, "$1")
    // Markdown links: read the visible text, drop the URL.
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1")
    // Headings.
    .replace(/^#+\s*/gm, "")
    // Bold/italic markers.
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/_([^_]+)_/g, "$1")
    // Block quote markers.
    .replace(/^>\s?/gm, "")
    // Bullet points / numbered lists.
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+\.\s+/gm, "")
    // Collapse extra whitespace.
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/**
 * Speak text via the configured provider's TTS, falling back to the
 * browser's ``speechSynthesis`` when the server returns 501 or fails.
 *
 * Two ways to feed it:
 *  - ``speak(text)`` — single shot: replace anything playing, say this,
 *    fire ``onEnd`` when done.
 *  - ``enqueue(chunk)`` repeatedly, then ``finish()`` — streaming: each
 *    chunk plays in order as it arrives; ``onEnd`` fires once, after the
 *    last queued chunk drains *and* ``finish()`` has been called. This
 *    lets the voice loop start talking on the first sentence while the
 *    assistant is still generating the rest.
 *
 * ``stop`` cancels everything (in-flight fetch, current audio, pending
 * queue) without firing ``onEnd`` — it's a deliberate interrupt.
 */
export function useSpeechPlayback(options: SpeechPlaybackOptions = {}) {
  const optsRef = useRef(options);
  optsRef.current = options;

  const synthRef = useRef<SpeechSynthesis | null>(null);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);
  const audioStateRef = useRef<{ audio: HTMLAudioElement; url: string } | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Streaming queue state. `genRef` is bumped by stop() so a chunk whose
  // network/playback was in flight when we interrupted can't resurrect
  // the pump after the queue was cleared.
  const queueRef = useRef<string[]>([]);
  const playingRef = useRef(false);
  const finishedRef = useRef(false);
  const genRef = useRef(0);
  // Chrome populates speechSynthesis.getVoices() asynchronously: the
  // first call right after page load returns []; voices arrive via the
  // `voiceschanged` event. Speaking an utterance with no voice loaded
  // is a silent no-op, so we cache the picked voice once it's ready and
  // hand it to every utterance.
  const voiceRef = useRef<SpeechSynthesisVoice | null>(null);

  const browserAvailable =
    typeof window !== "undefined" && "speechSynthesis" in window;
  const audioAvailable = typeof window !== "undefined" && typeof Audio !== "undefined";
  const initialAvailable = browserAvailable || audioAvailable;
  const [status, setStatus] = useState<SpeechStatus>(
    initialAvailable ? "idle" : "unavailable",
  );

  const stopServerAudio = useCallback(() => {
    const state = audioStateRef.current;
    if (!state) return;
    audioStateRef.current = null;
    try {
      // Detach handlers first: load() on a cleared <audio> can fire
      // 'error', which must not trigger the browser-voice fallback for
      // a chunk we're deliberately interrupting.
      state.audio.onended = null;
      state.audio.onerror = null;
      state.audio.pause();
      state.audio.removeAttribute("src");
      state.audio.load();
    } catch {
      /* noop */
    }
    URL.revokeObjectURL(state.url);
  }, []);

  const stopBrowser = useCallback(() => {
    const synth = synthRef.current;
    utteranceRef.current = null;
    if (!synth) return;
    try {
      synth.cancel();
    } catch {
      /* noop */
    }
  }, []);

  useEffect(() => {
    if (!browserAvailable) {
      return () => {
        abortRef.current?.abort();
        abortRef.current = null;
        stopServerAudio();
        stopBrowser();
      };
    }

    const synth = window.speechSynthesis;
    synthRef.current = synth;

    const pickVoice = () => {
      const voices = synth.getVoices();
      if (voices.length === 0) return;
      // Prefer en-US, then any English voice, then the platform default.
      const enUS = voices.find((v) => v.lang === "en-US");
      const en = enUS ?? voices.find((v) => v.lang.startsWith("en"));
      const fallback = voices.find((v) => v.default) ?? voices[0];
      voiceRef.current = en ?? fallback ?? null;
    };

    // First synchronous read — populated immediately on Safari/Firefox.
    pickVoice();
    // Chrome fires `voiceschanged` once the list is loaded.
    synth.addEventListener("voiceschanged", pickVoice);

    return () => {
      synth.removeEventListener("voiceschanged", pickVoice);
      abortRef.current?.abort();
      abortRef.current = null;
      stopServerAudio();
      stopBrowser();
    };
  }, [browserAvailable, stopBrowser, stopServerAudio]);

  const idleStatus = useCallback(() => {
    setStatus((s) => (s === "unavailable" ? s : "idle"));
  }, []);

  // Play one already-cleaned chunk through the browser's speech
  // synthesis. Resolves when the utterance ends (or errors) so the queue
  // pump can move to the next chunk; surfaces real errors via onError.
  const playBrowserItem = useCallback(
    (cleaned: string): Promise<void> =>
      new Promise((resolve) => {
        const synth = synthRef.current;
        if (!synth) {
          optsRef.current.onError?.(
            new Error("Speech synthesis is not available."),
          );
          resolve();
          return;
        }
        try {
          synth.cancel();
        } catch {
          /* noop */
        }
        const utter = new SpeechSynthesisUtterance(cleaned);
        utter.rate = parseVoicePlaybackSpeed(optsRef.current.playbackRate);
        if (voiceRef.current) {
          utter.voice = voiceRef.current;
          utter.lang = voiceRef.current.lang;
        }
        let settled = false;
        const done = () => {
          if (settled) return;
          settled = true;
          if (utteranceRef.current === utter) utteranceRef.current = null;
          resolve();
        };
        utter.onend = done;
        utter.onerror = (event) => {
          // Treat 'canceled'/'interrupted' as a deliberate stop.
          if (
            event.error &&
            event.error !== "canceled" &&
            event.error !== "interrupted"
          ) {
            console.warn("[useSpeechPlayback] browser TTS error:", event.error);
            optsRef.current.onError?.(new Error(event.error));
          }
          done();
        };
        utteranceRef.current = utter;
        try {
          synth.speak(utter);
        } catch (e) {
          optsRef.current.onError?.(
            e instanceof Error ? e : new Error(String(e)),
          );
          done();
        }
      }),
    [],
  );

  // Play one synthesised audio blob. Resolves when playback finishes;
  // on a decode/playback failure, falls back to the browser voice so the
  // user still hears the chunk, then resolves.
  const playServerBlobItem = useCallback(
    (blob: Blob, fallbackText: string): Promise<void> =>
      new Promise((resolve) => {
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audio.playbackRate = parseVoicePlaybackSpeed(optsRef.current.playbackRate);
        const state = { audio, url };
        audioStateRef.current = state;
        let settled = false;
        const cleanup = () => {
          if (audioStateRef.current === state) {
            audioStateRef.current = null;
          }
          URL.revokeObjectURL(url);
        };
        const finishOk = () => {
          if (settled) return;
          settled = true;
          cleanup();
          resolve();
        };
        const fallback = () => {
          if (settled) return;
          settled = true;
          // stop() (or a newer chunk) already tore this down — don't
          // resurrect it through the browser voice.
          if (audioStateRef.current !== state) {
            URL.revokeObjectURL(url);
            resolve();
            return;
          }
          cleanup();
          if (browserAvailable) {
            playBrowserItem(fallbackText).then(resolve);
          } else {
            optsRef.current.onError?.(new Error("Audio playback failed."));
            resolve();
          }
        };
        audio.onended = () => {
          if (audioStateRef.current !== state) {
            resolve();
            return;
          }
          finishOk();
        };
        audio.onerror = fallback;
        audio.play().catch(fallback);
      }),
    [browserAvailable, playBrowserItem],
  );

  // Synthesise + play one cleaned chunk, server first then browser
  // fallback. `gen` is the queue generation captured when the chunk was
  // dequeued; a stop() bumps it and aborts, so a chunk that loses the
  // race resolves without playing.
  const playChunk = useCallback(
    async (cleaned: string, gen: number): Promise<void> => {
      if (!audioAvailable) {
        if (gen !== genRef.current) return;
        await playBrowserItem(cleaned);
        return;
      }
      const ac = new AbortController();
      abortRef.current = ac;
      let result;
      try {
        result = await synthesizeSpeech(cleaned, ac.signal);
      } catch (e) {
        if (ac.signal.aborted || gen !== genRef.current) return;
        if (browserAvailable) {
          await playBrowserItem(cleaned);
        } else {
          optsRef.current.onError?.(
            e instanceof Error ? e : new Error(String(e)),
          );
        }
        return;
      }
      if (ac.signal.aborted || gen !== genRef.current) return;
      if (result == null) {
        // 501 — provider doesn't expose TTS, use the browser voice.
        if (browserAvailable) {
          await playBrowserItem(cleaned);
        } else {
          optsRef.current.onError?.(
            new Error("Speech synthesis is not available."),
          );
        }
        return;
      }
      await playServerBlobItem(result.audio, cleaned);
    },
    [audioAvailable, browserAvailable, playBrowserItem, playServerBlobItem],
  );

  // Drain the queue one chunk at a time. When it empties *and* finish()
  // has been called, the turn's speech is fully done — fire onEnd so the
  // voice loop resumes listening.
  const pump = useCallback(() => {
    if (playingRef.current) return;
    const next = queueRef.current.shift();
    if (next === undefined) {
      if (finishedRef.current) {
        finishedRef.current = false;
        idleStatus();
        optsRef.current.onEnd?.();
      }
      return;
    }
    playingRef.current = true;
    setStatus("speaking");
    const gen = genRef.current;
    void playChunk(next, gen).then(() => {
      playingRef.current = false;
      // A stop() during playback bumped the generation and cleared the
      // queue; don't pull the next (already-cleared) chunk.
      if (gen !== genRef.current) return;
      pump();
    });
  }, [idleStatus, playChunk]);

  const stop = useCallback(() => {
    genRef.current += 1;
    queueRef.current = [];
    finishedRef.current = false;
    playingRef.current = false;
    abortRef.current?.abort();
    abortRef.current = null;
    stopServerAudio();
    stopBrowser();
    idleStatus();
  }, [idleStatus, stopBrowser, stopServerAudio]);

  // Append a chunk to the speech queue. Starts playback immediately if
  // nothing is in flight. No-op when TTS is unavailable — the caller
  // detects that via `status` and keeps the loop moving itself.
  const enqueue = useCallback(
    (text: string) => {
      if (status === "unavailable") return;
      const cleaned = cleanForSpeech(text);
      if (!cleaned) return;
      queueRef.current.push(cleaned);
      if (!playingRef.current) pump();
    },
    [pump, status],
  );

  // Signal that no more chunks will be enqueued for this turn. onEnd
  // fires now if the queue already drained, otherwise when it does.
  const finish = useCallback(() => {
    finishedRef.current = true;
    if (!playingRef.current && queueRef.current.length === 0) {
      finishedRef.current = false;
      idleStatus();
      optsRef.current.onEnd?.();
    }
  }, [idleStatus]);

  // Single-shot convenience: replace anything playing with this one
  // utterance and fire onEnd when it finishes.
  const speak = useCallback(
    (text: string) => {
      stop();
      enqueue(text);
      finish();
      return true;
    },
    [enqueue, finish, stop],
  );

  return {
    status,
    speak,
    enqueue,
    finish,
    stop,
  };
}
