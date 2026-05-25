import { useState } from "react";
import { SettingsIcon, XIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { SettingsPanel } from "@/screens/Agent/SettingsPanel";
import { ChatScreen } from "@/screens/Chat/ChatScreen";

/**
 * Onboarding step 2: the agent walks the user through the chat ritual.
 *
 * If the credential entered in step 1 is wrong, the agent can't start —
 * and with no nav chrome and no back button the user would be trapped.
 * This wraps the chat with an always-available escape: reopen provider
 * settings, fix or clear the credential. No coordination needed —
 * clearing the only configured provider drops identity back to
 * `needs_provider`, and the 4s identity poll in `IdentityProvider`
 * flips the route on its own (this whole screen unmounts).
 */
export function OnboardingChatScreen() {
  const [showSettings, setShowSettings] = useState(false);

  return (
    <div className="relative flex h-full flex-col">
      <div className="flex items-center justify-between gap-3 border-b border-life-line bg-life-bg px-4 py-2">
        <span className="text-xs text-life-ink-3">
          Setting things up. Stuck — wrong key, agent not responding?
        </span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setShowSettings(true)}
        >
          <SettingsIcon className="size-4" />
          Provider settings
        </Button>
      </div>

      <div className="flex-1 overflow-hidden">
        <ChatScreen />
      </div>

      {showSettings && (
        <div className="absolute inset-0 z-20 flex flex-col bg-life-bg">
          <div className="flex items-center justify-between gap-3 border-b border-life-line px-4 py-3">
            <div>
              <h1 className="text-base font-semibold">Provider settings</h1>
              <p className="text-xs text-life-ink-3">
                Fix or clear the credential, then return to the chat.
              </p>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-label="Close provider settings"
              onClick={() => setShowSettings(false)}
            >
              <XIcon className="size-4" />
            </Button>
          </div>
          <div className="flex-1 overflow-hidden">
            <SettingsPanel />
          </div>
        </div>
      )}
    </div>
  );
}
