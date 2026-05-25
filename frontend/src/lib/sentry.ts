import * as Sentry from "@sentry/react";

export const SentryErrorBoundary = Sentry.ErrorBoundary;

function envNumber(raw: string | undefined, fallback: number): number {
  if (raw === undefined || raw === "") return fallback;

  const value = Number(raw);
  return Number.isFinite(value) ? value : fallback;
}

export function initSentry() {
  const dsn = import.meta.env.VITE_SENTRY_DSN;
  if (!dsn) return;

  Sentry.init({
    dsn,
    environment: import.meta.env.VITE_SENTRY_ENVIRONMENT ?? import.meta.env.MODE,
    release: import.meta.env.VITE_SENTRY_RELEASE,
    sendDefaultPii: false,
    integrations: [Sentry.browserTracingIntegration()],
    tracesSampleRate: envNumber(import.meta.env.VITE_SENTRY_TRACES_SAMPLE_RATE, 0),
    tracePropagationTargets: [/^\/api\//],
  });
}
