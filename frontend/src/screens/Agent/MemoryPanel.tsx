import { useCallback, useEffect, useState } from "react";

import { CoreMemoryEditor } from "@/screens/Knowledge/CoreMemoryEditor";
import {
  fetchSkills,
  type CoreMemoryName,
  type Skill,
} from "@/screens/Knowledge/knowledgeApi";
import { SkillView } from "@/screens/Knowledge/SkillView";
import { IconCaret, IconDoc } from "@/shell/icons";
import { useIdentity } from "@/shell/identity";
import { cn } from "@/lib/utils";

type View =
  | { kind: "list" }
  | { kind: "core"; name: CoreMemoryName }
  | { kind: "skill"; name: string };

export function MemoryPanel() {
  const { assistantName } = useIdentity();
  const [skills, setSkills] = useState<Skill[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>({ kind: "list" });

  const refresh = useCallback(async () => {
    try {
      setSkills(await fetchSkills());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (view.kind === "core") {
    return (
      <CoreMemoryEditor
        name={view.name}
        onBack={() => setView({ kind: "list" })}
      />
    );
  }

  if (view.kind === "skill") {
    return (
      <SkillView
        name={view.name}
        onBack={() => setView({ kind: "list" })}
      />
    );
  }

  return (
    <div className="flex h-full flex-col overflow-y-auto px-5 pb-6">
      <CoreMemoryCard
        assistantName={assistantName}
        onOpen={(name) => setView({ kind: "core", name })}
      />

      <SkillsCard
        skills={skills}
        error={error}
        assistantName={assistantName}
        onOpen={(name) => setView({ kind: "skill", name })}
      />
    </div>
  );
}

function CoreMemoryCard({
  assistantName,
  onOpen,
}: {
  assistantName: string;
  onOpen: (name: CoreMemoryName) => void;
}) {
  const coreLabels: Record<CoreMemoryName, { title: string; subtitle: string }> = {
    about_user: {
      title: "About you",
      subtitle: `Facts ${assistantName} should always know about you.`,
    },
    behavior: {
      title: `How ${assistantName} behaves`,
      subtitle: "Tone, style, collaboration norms.",
    },
  };
  return (
    <div className="mt-4 mb-4 rounded-2xl border border-life-line bg-life-card p-3.5">
      <div className="mb-2 flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.6px] text-life-ink-3">
        Core memory
      </div>
      <div className="flex flex-col">
        {(["about_user", "behavior"] as CoreMemoryName[]).map((name, i) => {
          const labels = coreLabels[name];
          return (
            <button
              key={name}
              type="button"
              onClick={() => onOpen(name)}
              className={cn(
                "flex items-start gap-3 rounded-lg px-1 py-2.5 text-left hover:bg-life-bg",
                i > 0 && "border-t border-life-line",
              )}
            >
              <span className="mt-0.5 text-life-accent">
                <IconDoc />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-life-ink">
                  {labels.title}
                </div>
                <div className="text-xs text-life-ink-3">
                  {labels.subtitle}
                </div>
              </div>
              <span className="mt-1 text-life-ink-3">
                <IconCaret />
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function SkillsCard({
  skills,
  error,
  assistantName,
  onOpen,
}: {
  skills: Skill[] | null;
  error: string | null;
  assistantName: string;
  onOpen: (name: string) => void;
}) {
  return (
    <div className="mt-2 mb-4 rounded-2xl border border-life-line bg-life-card p-3.5">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-[10px] font-bold uppercase tracking-[0.6px] text-life-ink-3">
          Skills
        </span>
        <span className="text-[10px] text-life-ink-3">read-only · agent-managed</span>
      </div>
      {error && (
        <div className="px-1 py-2 text-xs text-red-500">
          Couldn't load skills: {error}
        </div>
      )}
      {!error && skills === null && (
        <div className="px-1 py-2 text-xs text-life-ink-3">Loading…</div>
      )}
      {skills !== null && skills.length === 0 && (
        <div className="px-1 py-2 text-xs text-life-ink-3">
          None installed. Open the Chat tab and ask {assistantName} to add one.
        </div>
      )}
      {skills !== null && skills.length > 0 && (
        <div className="flex flex-col">
          {skills.map((s, i) => (
            <button
              key={s.name}
              type="button"
              onClick={() => onOpen(s.name)}
              className={cn(
                "flex items-start gap-3 rounded-lg px-1 py-2.5 text-left hover:bg-life-bg",
                i > 0 && "border-t border-life-line",
              )}
            >
              <span className="mt-0.5 text-life-accent">
                <IconDoc />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-life-ink truncate">
                  {s.name}
                </div>
                {s.description && (
                  <div className="text-xs text-life-ink-3 truncate">
                    {s.description}
                  </div>
                )}
              </div>
              <span className="mt-1 text-life-ink-3">
                <IconCaret />
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
