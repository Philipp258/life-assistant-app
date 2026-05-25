import type { ReactNode } from "react";

import { useIdentity } from "./identity";
import { TabBar } from "./TabBar";

type AppShellProps = {
  children: ReactNode;
};

/**
 * Mobile-first shell. Column fills the viewport on phones and caps at
 * 480px on desktop. Content area scrolls; the tab bar is a flex footer.
 *
 * During onboarding the tab bar is hidden so the new user only sees the
 * chat — no nav distractions until setup is done.
 *
 * Heights inherit from html/body/#root which are pinned to 100dvh in
 * index.css. Using h-full here (instead of repeating 100dvh) keeps the
 * shell from ever overflowing the locked document, so the TabBar stays
 * visible across viewport transitions (address bar, safe areas, etc.).
 */
export function AppShell({ children }: AppShellProps) {
  const { isOnboarding } = useIdentity();
  return (
    <div className="flex h-full w-full justify-center bg-[#E8E3D8]">
      <div className="relative flex h-full w-full max-w-[480px] flex-col overflow-hidden bg-life-bg text-life-ink">
        <div className="relative flex-1 overflow-hidden">{children}</div>
        {!isOnboarding && <TabBar />}
      </div>
    </div>
  );
}
