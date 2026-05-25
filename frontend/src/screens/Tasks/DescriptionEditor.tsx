import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

/**
 * Full-screen description editor. The description is the one long-form
 * field on a task; editing it inside the metadata sheet is cramped on
 * mobile, so it gets its own surface. Full-screen on phones, a large
 * centred panel on desktop. Commits explicitly (Save) — no blur-commit,
 * so a stray tap can't half-save a long note.
 */
export function DescriptionEditor({
  open,
  initialValue,
  onSave,
  onClose,
}: {
  open: boolean;
  initialValue: string;
  onSave: (next: string | null) => Promise<void> | void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState(initialValue);
  const [saving, setSaving] = useState(false);

  // Re-seed when (re)opened or the underlying task description changes.
  useEffect(() => {
    if (open) setDraft(initialValue);
  }, [open, initialValue]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const dirty = draft !== initialValue;

  const save = async () => {
    if (saving) return;
    setSaving(true);
    try {
      await onSave(draft.length ? draft : null);
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      data-testid="description-editor"
      className="fixed inset-0 z-40 flex flex-col bg-life-bg sm:items-center sm:justify-center sm:bg-black/40"
    >
      <div className="flex h-full w-full flex-col bg-life-bg sm:h-[80vh] sm:max-w-[640px] sm:rounded-2xl sm:shadow-xl">
        <div className="flex items-center justify-between border-b border-life-line px-4 py-3">
          <h2 className="font-serif text-[18px] text-life-ink">Description</h2>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={onClose}
              className="rounded-full"
            >
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              data-testid="description-editor-save"
              disabled={saving || !dirty}
              onClick={() => void save()}
              className="rounded-full"
            >
              Save
            </Button>
          </div>
        </div>
        <Textarea
          autoFocus
          aria-label="Description"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Write with Markdown…"
          className="min-h-0 flex-1 resize-none rounded-none border-0 bg-life-bg px-4 py-3 text-[14px] leading-relaxed focus-visible:ring-0"
        />
        <p className="border-t border-life-line px-4 py-2 text-[11px] text-life-ink-3">
          Markdown supported: headings, links, lists, checkboxes, code, tables.
        </p>
      </div>
    </div>
  );
}
