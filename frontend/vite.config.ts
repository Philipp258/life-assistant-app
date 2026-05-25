import path from "node:path";
import { fileURLToPath } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { viteStaticCopy } from "vite-plugin-static-copy";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// VAD assets need to live next to one another at runtime: the worklet,
// the Silero ONNX models, and the onnxruntime-web WASM files. Copy them
// flat into `dist/vad/` (and serve from `/vad/` in dev) so the in-page
// code can hand the library a stable, same-origin asset path. The
// `stripBase: true` rename collapses the source directory tree so we
// don't end up with `/vad/node_modules/...` URLs at runtime.
const vadAssetTargets = [
  {
    src: "node_modules/@ricky0123/vad-web/dist/vad.worklet.bundle.min.js",
    dest: "vad",
    rename: { stripBase: true as const },
  },
  {
    src: "node_modules/@ricky0123/vad-web/dist/silero_vad_v5.onnx",
    dest: "vad",
    rename: { stripBase: true as const },
  },
  {
    src: "node_modules/@ricky0123/vad-web/dist/silero_vad_legacy.onnx",
    dest: "vad",
    rename: { stripBase: true as const },
  },
  {
    src: "node_modules/onnxruntime-web/dist/*.wasm",
    dest: "vad",
    rename: { stripBase: true as const },
  },
  {
    src: "node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded*.mjs",
    dest: "vad",
    rename: { stripBase: true as const },
  },
];

// A monotonic, build-time identifier injected into both `index.html`
// (as a <meta>) and a runtime constant. The frontend uses it to spot
// "an old PWA shell is running against a newer deployed build" and
// trigger a safe reload. See `src/lib/build-check.ts` and issue #173.
const BUILD_ID = process.env.LIFE_ASSISTANT_BUILD_ID ?? String(Date.now());

const buildIdPlugin = {
  name: "life-assistant-build-id",
  transformIndexHtml(html: string) {
    const tag = `<meta name="life-assistant-build-id" content="${BUILD_ID}" />`;
    return html.replace("</head>", `    ${tag}\n  </head>`);
  },
};

// Storybook reuses this config but no story renders the voice recorder,
// and one of the onnxruntime-web WASM files is exactly 25 MiB — the hard
// asset-size limit for Cloudflare Workers — so shipping it in the Storybook
// bundle makes the Workers Build deploy step fail. Skip the VAD copy when
// Storybook is the consumer.
const isStorybook = process.env.STORYBOOK === "true";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    ...(isStorybook ? [] : [viteStaticCopy({ targets: vadAssetTargets })]),
    buildIdPlugin,
  ],
  define: {
    __LIFE_ASSISTANT_BUILD_ID__: JSON.stringify(BUILD_ID),
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: Number(process.env.FRONTEND_PORT ?? 5173),
    proxy: {
      "/api": {
        target: `http://localhost:${process.env.BACKEND_PORT ?? 8000}`,
        changeOrigin: true,
        // The chat channel (`/api/ws`) is a WebSocket upgrade; without
        // this the dev proxy 404s the handshake and the UI never gets a
        // live thread.
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
