import { ProviderSetupStepper } from "@/screens/Agent/SettingsPanel";

/**
 * First-run provider setup. Chat is required before the agent can run;
 * voice is optional and the setup screen advances explicitly when done.
 */
export function ProviderSetupScreen() {
  return (
    <div className="flex h-full flex-col bg-life-bg">
      <div className="flex-1 overflow-hidden">
        <ProviderSetupStepper />
      </div>
    </div>
  );
}
