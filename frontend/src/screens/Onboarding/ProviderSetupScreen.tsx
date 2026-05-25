import { SettingsPanel } from "@/screens/Agent/SettingsPanel";

/**
 * Step 1 of onboarding: pick a chat provider. The agent can't run
 * without one, so we render *only* this until the singleton config row
 * exists. Once it does, identity flips to `needs_chat` and the existing
 * chat-onboarding flow takes over.
 */
export function ProviderSetupScreen() {
  return (
    <div className="flex h-full flex-col bg-life-bg">
      <div className="border-b border-life-line px-4 py-4">
        <h1 className="text-base font-semibold">Welcome to Life Assistant</h1>
        <p className="text-xs text-life-ink-3">
          Pick a chat provider to get started. You can change it later under
          Agent → Settings. Need HTTPS without a domain? {" "}
          <a
            className="underline"
            href="/docs/https-no-domain.md"
            target="_blank"
            rel="noreferrer"
          >
            Open the setup guide
          </a>
          .
        </p>
      </div>
      <div className="flex-1 overflow-hidden">
        <SettingsPanel />
      </div>
    </div>
  );
}
