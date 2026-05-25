/**
 * Local-browser VAD (Silero via @ricky0123/vad-web), wrapped in a thin
 * interface the recorder hook can mock in tests and fall back from when
 * the model can't be loaded.
 *
 * Asset layout: the Vite build copies the worklet bundle, ONNX models,
 * and onnxruntime-web WASM into `/vad/` (see `vite.config.ts`), so the
 * runtime hands the library a stable same-origin path instead of the
 * default CDN.
 */

const VAD_ASSET_PATH = "/vad/";

export type VadEvents = {
  onSpeechStart: () => void;
  onSpeechEnd: () => void;
};

export type VadDetector = {
  /** Tear down the VAD without stopping the underlying media stream. */
  destroy: () => Promise<void>;
};

export type VadFactory = (
  stream: MediaStream,
  events: VadEvents,
) => Promise<VadDetector | null>;

let factoryOverride: VadFactory | null | undefined;

/** Test-only: force a specific factory (or `null` to simulate VAD load failure). */
export function __setVadFactoryForTests(
  factory: VadFactory | null | undefined,
): void {
  factoryOverride = factory;
}

let cachedRealFactory: VadFactory | null | undefined;

async function realSileroFactory(): Promise<VadFactory | null> {
  if (cachedRealFactory !== undefined) return cachedRealFactory;
  try {
    const mod = await import("@ricky0123/vad-web");
    const MicVAD = mod.MicVAD;
    cachedRealFactory = async (stream, events) => {
      try {
        const vad = await MicVAD.new({
          // We already own the mic stream (MediaRecorder also reads it).
          // Hand it to MicVAD via the stream callbacks; the no-op
          // pause/resume keeps MicVAD from tearing it down on us.
          getStream: async () => stream,
          pauseStream: async () => undefined,
          resumeStream: async () => stream,
          baseAssetPath: VAD_ASSET_PATH,
          onnxWASMBasePath: VAD_ASSET_PATH,
          onSpeechStart: () => events.onSpeechStart(),
          onSpeechEnd: () => events.onSpeechEnd(),
        });
        await vad.start();
        return {
          destroy: async () => {
            try {
              await vad.pause();
            } catch {
              /* noop */
            }
            try {
              await vad.destroy();
            } catch {
              /* noop */
            }
          },
        };
      } catch {
        return null;
      }
    };
    return cachedRealFactory;
  } catch {
    cachedRealFactory = null;
    return null;
  }
}

/**
 * Resolve the active VAD factory. Tests can override via
 * `__setVadFactoryForTests`; production lazy-loads the real Silero
 * implementation. Returns `null` when no VAD is available — callers
 * should fall back to the RMS-based silence detector.
 */
export async function getVadFactory(): Promise<VadFactory | null> {
  if (factoryOverride !== undefined) return factoryOverride;
  return realSileroFactory();
}
