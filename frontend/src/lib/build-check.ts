// Detect when the installed PWA is running an older app shell than the
// one currently deployed and quietly reload onto the new build. See
// issue #173.
//
// How it works:
//   1. vite.config.ts stamps every build with a `BUILD_ID` and writes
//      it into both `index.html` (as <meta name="life-assistant-build-id">) and
//      a `__LIFE_ASSISTANT_BUILD_ID__` global.
//   2. When the document becomes visible (the user re-foregrounds the
//      PWA), we refetch `/index.html` with `cache: "no-store"` and
//      compare the meta tag against our compile-time constant.
//   3. On mismatch we ask the service worker (if any) to update and
//      then `location.reload()`. We only reload after the document has
//      been hidden long enough to confidently say the user wasn't
//      mid-interaction — otherwise we just arm a flag and wait for the
//      next foreground.
//
// We intentionally do not poll while visible: an unexpected reload
// during typing is worse than the staleness it would prevent.

declare const __LIFE_ASSISTANT_BUILD_ID__: string;

const HIDDEN_RELOAD_THRESHOLD_MS = 60_000;
const MIN_CHECK_INTERVAL_MS = 60_000;

interface BuildCheckHooks {
  // Optional injection point for tests so they can drive the timing
  // without monkey-patching globals.
  now?: () => number;
  reload?: () => void;
}

export function installBuildCheck(hooks: BuildCheckHooks = {}): () => void {
  if (typeof document === "undefined") return () => {};
  const currentId = __LIFE_ASSISTANT_BUILD_ID__;
  if (!currentId) return () => {};

  const now = hooks.now ?? (() => Date.now());
  const reload =
    hooks.reload ??
    (() => {
      window.location.reload();
    });

  let checking = false;
  let lastCheckedAt = 0;
  let hiddenSince: number | null =
    document.visibilityState === "hidden" ? now() : null;
  let pendingNewBuild = false;

  const detectLatestId = async (): Promise<string | null> => {
    const r = await fetch("/index.html", {
      cache: "no-store",
      credentials: "same-origin",
    });
    if (!r.ok) return null;
    const html = await r.text();
    const match = html.match(
      /<meta[^>]*name=["']life-assistant-build-id["'][^>]*content=["']([^"']+)["']/i,
    );
    return match ? match[1] : null;
  };

  const tryReload = async () => {
    // Best-effort: bump the service worker so its push handlers are not
    // left over from the old build. Failure here is harmless — we still
    // reload the document, and the SW gets re-registered on next push
    // opt-in anyway.
    if ("serviceWorker" in navigator) {
      try {
        const reg = await navigator.serviceWorker.getRegistration();
        await reg?.update();
      } catch {
        // ignore
      }
    }
    reload();
  };

  const check = async () => {
    if (checking) return;
    if (document.visibilityState !== "visible") return;
    const ts = now();
    if (ts - lastCheckedAt < MIN_CHECK_INTERVAL_MS) return;
    checking = true;
    lastCheckedAt = ts;
    try {
      const latest = await detectLatestId();
      if (latest && latest !== currentId) {
        pendingNewBuild = true;
        const hiddenFor =
          hiddenSince === null ? Infinity : now() - hiddenSince;
        if (hiddenFor >= HIDDEN_RELOAD_THRESHOLD_MS) {
          await tryReload();
        }
        // Otherwise wait for the next hide → show cycle.
      }
    } catch {
      // Network blip; try again on next visibility flip.
    } finally {
      checking = false;
    }
  };

  const onVisibility = () => {
    if (document.visibilityState === "hidden") {
      hiddenSince = now();
      return;
    }
    const wasHiddenFor =
      hiddenSince === null ? 0 : now() - hiddenSince;
    hiddenSince = null;
    if (pendingNewBuild && wasHiddenFor >= HIDDEN_RELOAD_THRESHOLD_MS) {
      void tryReload();
      return;
    }
    void check();
  };

  document.addEventListener("visibilitychange", onVisibility);

  return () => {
    document.removeEventListener("visibilitychange", onVisibility);
  };
}
