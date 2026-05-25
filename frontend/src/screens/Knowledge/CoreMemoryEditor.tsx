import { useCallback, useEffect, useRef, useState } from "react";

import { MarkdownView } from "@/components/MarkdownView";
import { IconPencil } from "@/shell/icons";
import { useIdentity } from "@/shell/identity";

import {
  fetchCoreMemory,
  saveCoreMemory,
  type CoreMemoryName,
} from "./knowledgeApi";

const AUTOSAVE_MS = 500;

type State =
  | { kind: "loading" }
  | { kind: "ready"; saved: string }
  | { kind: "error"; message: string };

export function CoreMemoryEditor({
  name,
  onBack,
}: {
  name: CoreMemoryName;
  onBack: () => void;
}) {
  const { assistantName } = useIdentity();
  const titles: Record<CoreMemoryName, string> = {
    about_user: "About you",
    behavior: `How ${assistantName} behaves`,
  };
  const subtitles: Record<CoreMemoryName, string> = {
    about_user:
      `Loaded into ${assistantName}'s prompt every turn. Keep it tight - long context is paid every message.`,
    behavior:
      `How ${assistantName} should write, what tone to use, what to avoid. Loaded every turn.`,
  };
  const [state, setState] = useState<State>({ kind: "loading" });
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [mode, setMode] = useState<"view" | "edit">("view");

  const saveTimer = useRef<number | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    fetchCoreMemory(name)
      .then((res) => {
        if (cancelled) return;
        setState({ kind: "ready", saved: res.body });
        setDraft(res.body);
      })
      .catch((e) => {
        if (cancelled) return;
        setState({
          kind: "error",
          message: e instanceof Error ? e.message : String(e),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [name]);

  const flush = useCallback(
    async (latest: string) => {
      setSaving(true);
      try {
        const res = await saveCoreMemory(name, latest);
        setState({ kind: "ready", saved: res.body });
        setSavedAt(new Date());
      } catch (e) {
        setState({
          kind: "error",
          message: e instanceof Error ? e.message : String(e),
        });
      } finally {
        setSaving(false);
      }
    },
    [name],
  );

  useEffect(() => {
    if (state.kind !== "ready") return;
    if (draft === state.saved) return;
    if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      void flush(draft);
    }, AUTOSAVE_MS);
    return () => {
      if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    };
  }, [draft, state, flush]);

  const enterEdit = useCallback(() => {
    setMode("edit");
    window.requestAnimationFrame(() => {
      const ta = textareaRef.current;
      if (ta) {
        ta.focus();
        const len = ta.value.length;
        ta.setSelectionRange(len, len);
      }
    });
  }, []);

  const exitEdit = useCallback(async () => {
    if (saveTimer.current !== null) {
      window.clearTimeout(saveTimer.current);
      saveTimer.current = null;
    }
    if (state.kind === "ready" && draft !== state.saved) {
      await flush(draft);
    }
    setMode("view");
  }, [state, draft, flush]);

  if (state.kind === "loading") {
    return (
      <div className="flex h-full items-center justify-center text-sm text-life-ink-3">
        Loading…
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
        <div className="text-sm text-red-500">
          Couldn't load: {state.message}
        </div>
        <button
          type="button"
          onClick={onBack}
          className="text-xs text-life-ink-3 underline"
        >
          Back
        </button>
      </div>
    );
  }

  const isEdit = mode === "edit";
  return (
    <div className="flex h-full flex-col bg-life-bg">
      <div className="border-b border-life-line bg-life-card px-5 pt-3 pb-3">
        <div className="flex items-center gap-2 text-xs text-life-ink-3">
          <button
            type="button"
            onClick={onBack}
            className="rounded px-1 py-0.5 hover:bg-life-bg"
          >
            ← Back
          </button>
          <span className="ml-auto">
            {saving
              ? "Saving…"
              : savedAt
                ? `Saved ${savedAt.toLocaleTimeString(undefined, {
                    hour: "numeric",
                    minute: "2-digit",
                  })}`
                : ""}
          </span>
          {isEdit ? (
            <button
              type="button"
              onClick={() => void exitEdit()}
              className="rounded px-2 py-0.5 text-[12px] font-medium text-life-accent hover:bg-life-bg"
            >
              Done
            </button>
          ) : (
            <button
              type="button"
              onClick={enterEdit}
              aria-label="Edit"
              className="rounded p-1 text-life-ink-3 hover:bg-life-bg hover:text-life-accent"
            >
              <IconPencil />
            </button>
          )}
        </div>
        <div className="mt-2 font-serif text-[24px] leading-tight text-life-ink">
          {titles[name]}
        </div>
        <div className="text-xs text-life-ink-3">{subtitles[name]}</div>
      </div>
      {isEdit ? (
        <textarea
          ref={textareaRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Write…"
          className="flex-1 resize-none bg-transparent px-5 py-4 text-sm leading-relaxed text-life-ink-2 focus:outline-none"
          aria-label={titles[name]}
        />
      ) : (
        <div
          role="button"
          tabIndex={0}
          onClick={enterEdit}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              enterEdit();
            }
          }}
          className="flex-1 cursor-text overflow-y-auto bg-transparent px-5 py-4 text-sm leading-relaxed text-life-ink-2"
          aria-label={`Edit ${titles[name]}`}
        >
          {draft.trim() ? (
            <MarkdownView source={draft} />
          ) : (
            <span className="text-life-ink-3">Empty. Tap to edit.</span>
          )}
        </div>
      )}
    </div>
  );
}
