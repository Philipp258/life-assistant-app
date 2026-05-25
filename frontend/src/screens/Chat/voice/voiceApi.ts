import { apiFetch } from "@/lib/api";

export type VoiceTranscriptionResult = {
  text: string;
  provider: string;
  model: string;
};

/**
 * Map a recorded `Blob.type` (e.g. `audio/webm;codecs=opus`) to a sane
 * filename + extension. The backend infers the audio format from the
 * upload's `Content-Type`, so the filename is purely cosmetic.
 */
export function inferAudioFilename(mime: string | undefined): string {
  if (!mime) return "clip.webm";
  const primary = mime.split(";", 1)[0]?.trim().toLowerCase() ?? "";
  if (primary.includes("mp4") || primary.includes("m4a")) return "clip.mp4";
  if (primary.includes("ogg")) return "clip.ogg";
  if (primary.includes("mpeg") || primary.includes("mp3")) return "clip.mp3";
  if (primary.includes("wav")) return "clip.wav";
  if (primary.includes("flac")) return "clip.flac";
  return "clip.webm";
}

/**
 * Send a recorded audio blob to the backend for transcription. Throws
 * with the server-provided detail string when the request fails so the
 * caller can render a useful message in the voice mode bar.
 */
export async function transcribeAudio(
  blob: Blob,
): Promise<VoiceTranscriptionResult> {
  const filename = inferAudioFilename(blob.type);
  const form = new FormData();
  form.append("file", blob, filename);

  const r = await apiFetch("/api/voice/transcribe", {
    method: "POST",
    body: form,
  });
  if (!r.ok) {
    const detail = await extractDetail(r);
    throw new Error(detail ?? `Transcription failed (${r.status})`);
  }
  return (await r.json()) as VoiceTranscriptionResult;
}

async function extractDetail(r: Response): Promise<string | undefined> {
  try {
    const body = (await r.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail.length > 0) {
      return body.detail;
    }
  } catch {
    // Non-JSON error body — fall through.
  }
  return undefined;
}

export type SpeechSynthesisResult = {
  audio: Blob;
  contentType: string;
  provider: string;
  model: string;
};

/**
 * Ask the backend to synthesise speech via the configured provider.
 * Returns ``null`` when the server returns 501 — the caller should fall
 * back to the browser's built-in ``speechSynthesis``. Throws for any
 * other failure so the UI can surface a real error message.
 */
export async function synthesizeSpeech(
  text: string,
  signal?: AbortSignal,
): Promise<SpeechSynthesisResult | null> {
  const r = await apiFetch("/api/voice/synthesize", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
    signal,
  });
  if (r.status === 501) return null;
  if (!r.ok) {
    const detail = await extractDetail(r);
    throw new Error(detail ?? `Speech synthesis failed (${r.status})`);
  }
  const audio = await r.blob();
  return {
    audio,
    contentType: r.headers.get("content-type") ?? "audio/mpeg",
    provider: r.headers.get("x-voice-provider") ?? "unknown",
    model: r.headers.get("x-voice-model") ?? "unknown",
  };
}
