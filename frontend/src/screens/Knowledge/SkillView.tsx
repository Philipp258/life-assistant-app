import { useEffect, useState } from "react";

import { MarkdownView } from "@/components/MarkdownView";
import { IconCaret } from "@/shell/icons";
import { useIdentity } from "@/shell/identity";

import { fetchSkill, type SkillRead } from "./knowledgeApi";

type State =
  | { kind: "loading" }
  | { kind: "ready"; skill: SkillRead }
  | { kind: "error"; message: string };

export function SkillView({
  name,
  onBack,
}: {
  name: string;
  onBack: () => void;
}) {
  const { assistantName } = useIdentity();
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    fetchSkill(name)
      .then((skill) => {
        if (!cancelled) setState({ kind: "ready", skill });
      })
      .catch((e) => {
        if (!cancelled) {
          setState({
            kind: "error",
            message: e instanceof Error ? e.message : String(e),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [name]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-2 border-b border-life-line px-4 py-3">
        <button
          type="button"
          onClick={onBack}
          aria-label="Back"
          className="rounded p-1 text-life-ink-3 hover:bg-life-bg"
        >
          <span className="block rotate-180">
            <IconCaret />
          </span>
        </button>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-life-ink truncate">
            {name}
          </div>
          {state.kind === "ready" && state.skill.description && (
            <div className="text-[11px] text-life-ink-3 truncate">
              {state.skill.description}
            </div>
          )}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        <div className="mb-3 rounded-lg border border-life-line bg-life-card px-3 py-2 text-[12px] text-life-ink-3">
          Read-only - open the Chat tab and ask {assistantName} to edit this skill.
        </div>

        {state.kind === "loading" && (
          <div className="py-10 text-center text-sm text-life-ink-3">
            Loading…
          </div>
        )}

        {state.kind === "error" && (
          <div className="py-10 text-center text-sm text-red-500">
            Couldn't load skill: {state.message}
          </div>
        )}

        {state.kind === "ready" && (
          <MarkdownView source={state.skill.body} />
        )}
      </div>
    </div>
  );
}
