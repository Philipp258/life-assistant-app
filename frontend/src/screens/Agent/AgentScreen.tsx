import { useCallback, useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { cn } from "@/lib/utils";

import { MemoryPanel } from "./MemoryPanel";
import { NotificationsPanel } from "./NotificationsPanel";
import { SettingsPanel } from "./SettingsPanel";

type Tab = "memory" | "settings" | "notifications";

const TABS: ReadonlyArray<{ id: Tab; label: string }> = [
  { id: "memory", label: "Memory" },
  { id: "settings", label: "Settings" },
  { id: "notifications", label: "Notifications" },
];

const TAB_IDS = new Set<Tab>(TABS.map((t) => t.id));
const DEFAULT_TAB: Tab = "memory";

export function AgentScreen() {
  const navigate = useNavigate();
  const params = useParams<{ tab?: string }>();
  // `/agent` (no segment) lands on the default tab; an unknown segment
  // gets the same treatment so a stale URL does not blank the screen.
  const tab = useMemo<Tab>(() => {
    const raw = params.tab;
    return raw && TAB_IDS.has(raw as Tab) ? (raw as Tab) : DEFAULT_TAB;
  }, [params.tab]);
  const setTab = useCallback(
    (next: Tab) => {
      if (next === tab) return;
      navigate(next === DEFAULT_TAB ? "/agent" : `/agent/${next}`);
    },
    [navigate, tab],
  );

  return (
    <div className="flex h-full flex-col bg-life-bg">
      <header className="flex items-center gap-1 border-b border-life-line px-2 py-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm transition-colors",
              tab === t.id
                ? "bg-life-ink text-life-bg"
                : "text-life-ink-3 hover:text-life-ink",
            )}
          >
            {t.label}
          </button>
        ))}
      </header>
      <div className="flex-1 overflow-hidden">
        {tab === "memory" && <MemoryPanel />}
        {tab === "settings" && <SettingsPanel />}
        {tab === "notifications" && <NotificationsPanel />}
      </div>
    </div>
  );
}
