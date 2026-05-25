import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./index.css";
import { installBuildCheck } from "./lib/build-check";
import { initSentry, SentryErrorBoundary } from "./lib/sentry";

initSentry();

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("#root not found");

createRoot(rootEl).render(
  <StrictMode>
    <SentryErrorBoundary fallback={<div>Something went wrong.</div>}>
      <App />
    </SentryErrorBoundary>
  </StrictMode>,
);

// Watch for "PWA is running an old app shell after a deploy" and
// reload onto the new build when the user re-foregrounds the app.
installBuildCheck();
