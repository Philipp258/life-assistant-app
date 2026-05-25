import { apiFetch, jsonOrThrow } from "@/lib/api";

export type RuntimeSettings = {
  brave_api_key: string;
  vad_timeout_ms: string;
  voice_playback_speed: string;
};

export const DEFAULT_VOICE_PLAYBACK_SPEED = 1.15;
export const MIN_VOICE_PLAYBACK_SPEED = 0.5;
export const MAX_VOICE_PLAYBACK_SPEED = 2;

export function parseVoicePlaybackSpeed(value: string | number | null | undefined): number {
  if (value === null || value === undefined || value === "") {
    return DEFAULT_VOICE_PLAYBACK_SPEED;
  }
  const speed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(speed)) {
    return DEFAULT_VOICE_PLAYBACK_SPEED;
  }
  return Math.min(MAX_VOICE_PLAYBACK_SPEED, Math.max(MIN_VOICE_PLAYBACK_SPEED, speed));
}

export async function getRuntimeSettings(): Promise<RuntimeSettings> {
  const r = await apiFetch("/api/settings/runtime");
  return jsonOrThrow<RuntimeSettings>(r);
}

export async function putRuntimeSetting(
  key: keyof RuntimeSettings,
  value: string,
): Promise<{ key: string; value: string }> {
  const r = await apiFetch(`/api/settings/runtime/${key}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  if (!r.ok) {
    const detail = await r
      .json()
      .then((b: { detail?: string }) => b.detail)
      .catch(() => undefined);
    throw new Error(detail ?? `${r.status} ${r.statusText}`);
  }
  return (await r.json()) as { key: string; value: string };
}
