import { useEffect, useState } from "react";

import { getSlashCommands, type SlashCommandSpec } from "@/screens/Chat/chatApi";

let cached: SlashCommandSpec[] | null = null;
let inflight: Promise<SlashCommandSpec[]> | null = null;

export function useSlashCommands(): SlashCommandSpec[] {
  const [commands, setCommands] = useState<SlashCommandSpec[]>(cached ?? []);

  useEffect(() => {
    if (cached) return;
    if (!inflight) {
      inflight = getSlashCommands().then((list) => {
        cached = list;
        return list;
      });
    }
    let cancelled = false;
    inflight.then((list) => {
      if (!cancelled) setCommands(list);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return commands;
}

export function parseSlashPrefix(text: string): string | null {
  const stripped = text.trimStart();
  if (!stripped.startsWith("/")) return null;
  const body = stripped.slice(1);
  if (body.length === 0) return "";
  if (/\s/.test(body)) return null;
  return body;
}

export function SlashMenu({
  text,
  activeIndex,
  matches,
  onSelect,
}: {
  text: string;
  activeIndex: number;
  matches: SlashCommandSpec[];
  onSelect: (cmd: SlashCommandSpec) => void;
}) {
  if (parseSlashPrefix(text) === null || matches.length === 0) return null;

  return (
    <div
      role="listbox"
      aria-label="Slash commands"
      className="absolute bottom-full left-0 z-50 mb-2 min-w-56 overflow-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-md"
    >
      {matches.map((cmd, i) => (
        <button
          key={cmd.name}
          type="button"
          role="option"
          aria-selected={i === activeIndex}
          onMouseDown={(e) => {
            e.preventDefault();
            onSelect(cmd);
          }}
          className={
            "flex w-full flex-col items-start rounded-sm px-2 py-1.5 text-left text-sm outline-none " +
            (i === activeIndex
              ? "bg-accent text-accent-foreground"
              : "hover:bg-accent hover:text-accent-foreground")
          }
        >
          <span className="font-medium">/{cmd.name}</span>
          <span className="text-muted-foreground text-xs">
            {cmd.description}
          </span>
        </button>
      ))}
    </div>
  );
}
