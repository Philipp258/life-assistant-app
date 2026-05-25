import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { cn } from "@/lib/utils";

import { IconAgent, IconBook, IconChat, IconTask } from "./icons";

type Tab = { to: string; label: string; icon: ReactNode };

const TABS: Tab[] = [
  { to: "/chat", label: "Chat", icon: <IconChat /> },
  { to: "/tasks", label: "Tasks", icon: <IconTask /> },
  { to: "/know", label: "Knowledge", icon: <IconBook /> },
  { to: "/agent", label: "Agent", icon: <IconAgent /> },
];

export function TabBar() {
  const location = useLocation();
  const [lastTasksTo, setLastTasksTo] = useState("/tasks");

  useEffect(() => {
    if (location.pathname === "/tasks") {
      setLastTasksTo(`${location.pathname}${location.search}`);
    }
  }, [location.pathname, location.search]);

  return (
    <nav
      className="flex shrink-0 border-t border-life-line bg-life-card/90 px-1.5 pt-2 backdrop-blur-xl"
      style={{ paddingBottom: "calc(8px + env(safe-area-inset-bottom))" }}
    >
      {TABS.map((t) => (
        <NavLink
          key={t.to}
          to={t.to === "/tasks" ? lastTasksTo : t.to}
          className={({ isActive }) =>
            cn(
              "relative flex min-h-[54px] flex-1 flex-col items-center justify-center gap-0.5 rounded-2xl",
              isActive ? "bg-life-card text-life-accent" : "text-life-ink-3",
            )
          }
        >
          <span className="relative">{t.icon}</span>
          <span className="text-[10px] font-semibold tracking-[0.2px]">
            {t.label}
          </span>
        </NavLink>
      ))}
    </nav>
  );
}
