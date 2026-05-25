import { useCallback, useEffect, useRef, useState } from "react";

import { MarkdownView } from "@/components/MarkdownView";
import { IconPencil, IconTrash } from "@/shell/icons";
import { cn } from "@/lib/utils";

import {
  deleteKnowledge,
  fetchKnowledge,
  moveKnowledge,
  saveKnowledge,
  slugify,
  type Knowledge,
} from "./knowledgeApi";

const AUTOSAVE_MS = 500;

type State =
  | { kind: "loading" }
  | { kind: "ready"; item: Knowledge }
  | { kind: "error"; message: string };

export function KnowledgeEditor({
  path,
  onBack,
  onDeleted,
}: {
  path: string;
  onBack: () => void;
  onDeleted: () => void;
}) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [titleDraft, setTitleDraft] = useState("");
  const [bodyDraft, setBodyDraft] = useState("");
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [livePath, setLivePath] = useState(path);
  const [mode, setMode] = useState<"view" | "edit">("view");

  const saveTimer = useRef<number | null>(null);
  const bodyTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const titleInputRef = useRef<HTMLInputElement | null>(null);

  // Initial load — and reload when livePath changes (after rename).
  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    fetchKnowledge(livePath)
      .then((item) => {
        if (cancelled) return;
        setState({ kind: "ready", item });
        setTitleDraft(item.title);
        setBodyDraft(item.body);
        setSavedAt(item.updated);
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
  }, [livePath]);

  const flush = useCallback(
    async (
      latestTitle: string,
      latestBody: string,
      current: Knowledge,
    ) => {
      const titleChanged = latestTitle.trim() !== current.title;
      const bodyChanged = latestBody !== current.body;
      if (!titleChanged && !bodyChanged) return;
      setSaving(true);
      try {
        const updated = await saveKnowledge(
          current.path,
          latestBody,
          titleChanged ? latestTitle.trim() : null,
        );
        setState({ kind: "ready", item: updated });
        setSavedAt(updated.updated);
      } catch (e) {
        // Keep the draft; surface the failure but don't block typing.
        setState({
          kind: "error",
          message: e instanceof Error ? e.message : String(e),
        });
      } finally {
        setSaving(false);
      }
    },
    [],
  );

  // Debounced autosave on draft changes.
  useEffect(() => {
    if (state.kind !== "ready") return;
    const titleChanged = titleDraft.trim() !== state.item.title;
    const bodyChanged = bodyDraft !== state.item.body;
    if (!titleChanged && !bodyChanged) return;
    if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      void flush(titleDraft, bodyDraft, state.item);
    }, AUTOSAVE_MS);
    return () => {
      if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    };
  }, [titleDraft, bodyDraft, state, flush]);

  // Flush pending edits before unmount.
  useEffect(() => {
    return () => {
      if (saveTimer.current !== null) {
        window.clearTimeout(saveTimer.current);
      }
    };
  }, []);

  const handleRename = useCallback(async () => {
    if (state.kind !== "ready") return;
    const newTitle = titleDraft.trim();
    if (!newTitle) return;
    const newSlug = slugify(newTitle);
    const segs = state.item.path.split("/");
    const oldFile = segs[segs.length - 1];
    const newFile = `${newSlug}.md`;
    if (oldFile === newFile) return;
    const newPath = [...segs.slice(0, -1), newFile].join("/");
    try {
      // Save any pending body before moving.
      if (bodyDraft !== state.item.body) {
        await saveKnowledge(state.item.path, bodyDraft, newTitle);
      }
      const moved = await moveKnowledge(state.item.path, newPath);
      setLivePath(moved.path);
    } catch (e) {
      window.alert(e instanceof Error ? e.message : String(e));
    }
  }, [state, titleDraft, bodyDraft]);

  const enterEdit = useCallback(
    (focus: "title" | "body" = "body") => {
      setMode("edit");
      // Focus after the next paint so the input/textarea is mounted.
      window.requestAnimationFrame(() => {
        if (focus === "title") titleInputRef.current?.focus();
        else {
          const ta = bodyTextareaRef.current;
          if (ta) {
            ta.focus();
            const len = ta.value.length;
            ta.setSelectionRange(len, len);
          }
        }
      });
    },
    [],
  );

  const exitEdit = useCallback(async () => {
    if (saveTimer.current !== null) {
      window.clearTimeout(saveTimer.current);
      saveTimer.current = null;
    }
    if (state.kind === "ready") {
      await flush(titleDraft, bodyDraft, state.item);
    }
    setMode("view");
  }, [state, titleDraft, bodyDraft, flush]);

  const handleDelete = useCallback(async () => {
    if (state.kind !== "ready") return;
    if (!window.confirm(`Delete "${state.item.title}"?`)) return;
    try {
      await deleteKnowledge(state.item.path);
      onDeleted();
    } catch (e) {
      window.alert(e instanceof Error ? e.message : String(e));
    }
  }, [state, onDeleted]);

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
          Couldn't load knowledge: {state.message}
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

  const item = state.item;
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
            ← Knowledge
          </button>
          <span className="ml-auto">
            {saving
              ? "Saving…"
              : savedAt
                ? `Saved ${formatTime(savedAt)}`
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
              onClick={() => enterEdit("body")}
              aria-label="Edit"
              className="rounded p-1 text-life-ink-3 hover:bg-life-bg hover:text-life-accent"
            >
              <IconPencil />
            </button>
          )}
          <button
            type="button"
            onClick={handleDelete}
            aria-label="Delete"
            className="rounded p-1 text-life-ink-3 hover:bg-life-bg hover:text-red-500"
          >
            <IconTrash />
          </button>
        </div>
        {isEdit ? (
          <input
            ref={titleInputRef}
            value={titleDraft}
            onChange={(e) => setTitleDraft(e.target.value)}
            onBlur={handleRename}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            }}
            placeholder="Title"
            className={cn(
              "mt-2 w-full bg-transparent font-serif text-[24px] leading-tight text-life-ink",
              "focus:outline-none",
            )}
            aria-label="Title"
          />
        ) : (
          <button
            type="button"
            onClick={() => enterEdit("title")}
            className="mt-2 w-full bg-transparent text-left font-serif text-[24px] leading-tight text-life-ink"
            aria-label="Edit title"
          >
            {titleDraft || (
              <span className="text-life-ink-3">Untitled</span>
            )}
          </button>
        )}
        <div className="text-[10px] text-life-ink-3">{item.path}</div>
      </div>
      {isEdit ? (
        <textarea
          ref={bodyTextareaRef}
          value={bodyDraft}
          onChange={(e) => setBodyDraft(e.target.value)}
          placeholder="Write…"
          className="flex-1 resize-none bg-transparent px-5 py-4 text-sm leading-relaxed text-life-ink-2 focus:outline-none"
          aria-label="Body"
        />
      ) : (
        <div
          role="button"
          tabIndex={0}
          onClick={() => enterEdit("body")}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              enterEdit("body");
            }
          }}
          className="flex-1 cursor-text overflow-y-auto bg-transparent px-5 py-4 text-sm leading-relaxed text-life-ink-2"
          aria-label="Edit body"
        >
          {bodyDraft.trim() ? (
            <MarkdownView source={bodyDraft} />
          ) : (
            <span className="text-life-ink-3">
              Empty. Tap to edit.
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}
