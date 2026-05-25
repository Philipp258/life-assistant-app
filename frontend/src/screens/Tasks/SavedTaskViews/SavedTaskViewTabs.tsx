import {
  ChevronLeft,
  ChevronRight,
  MoreHorizontal,
  Plus,
} from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { cn } from "@/lib/utils";

import type { SavedTaskView } from "../savedTaskViewsApi";

type Props = {
  views: SavedTaskView[];
  activeId: number;
  dirty: boolean;
  onSelect: (id: number) => void;
  onRename: (id: number, name: string) => void;
  onMakeDefault: (id: number) => void;
  onDelete: (id: number) => void;
  onReorder: (orderedIds: number[]) => void;
  onAdd: () => void;
};

const MENU_WIDTH = 200;
const DRAG_MIME = "application/x-task-view-id";

export function SavedTaskViewTabs({
  views,
  activeId,
  dirty,
  onSelect,
  onRename,
  onMakeDefault,
  onDelete,
  onReorder,
  onAdd,
}: Props) {
  const [menuFor, setMenuFor] = useState<number | null>(null);
  const [menuAnchor, setMenuAnchor] = useState<{ top: number; left: number } | null>(null);
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [dragId, setDragId] = useState<number | null>(null);
  const [dragOverId, setDragOverId] = useState<number | null>(null);

  useEffect(() => {
    if (menuFor === null) return;
    function onDocClick(event: MouseEvent) {
      const target = event.target as Element | null;
      if (target?.closest("[data-saved-task-view-menu]")) return;
      setMenuFor(null);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setMenuFor(null);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuFor]);

  function openMenu(id: number, anchor: HTMLElement) {
    const rect = anchor.getBoundingClientRect();
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - 8 - MENU_WIDTH));
    setMenuFor(id);
    setMenuAnchor({ top: rect.bottom + 4, left });
  }

  function startRename(view: SavedTaskView) {
    setRenamingId(view.id);
    setRenameDraft(view.name);
    setMenuFor(null);
  }

  function commitRename() {
    if (renamingId !== null && renameDraft.trim()) {
      onRename(renamingId, renameDraft.trim());
    }
    setRenamingId(null);
  }

  function moveBy(id: number, delta: number) {
    const idx = views.findIndex((v) => v.id === id);
    if (idx < 0) return;
    const target = idx + delta;
    if (target < 0 || target >= views.length) return;
    const next = views.map((v) => v.id);
    [next[idx], next[target]] = [next[target], next[idx]];
    onReorder(next);
    setMenuFor(null);
  }

  function moveBefore(sourceId: number, targetId: number) {
    if (sourceId === targetId) return;
    const ids = views.map((v) => v.id).filter((id) => id !== sourceId);
    const targetIdx = ids.indexOf(targetId);
    if (targetIdx < 0) return;
    ids.splice(targetIdx, 0, sourceId);
    onReorder(ids);
  }

  const menuView = menuFor !== null ? views.find((v) => v.id === menuFor) : null;
  const menuIdx = menuView ? views.findIndex((v) => v.id === menuView.id) : -1;

  return (
    <div
      className="flex items-center gap-1.5 overflow-x-auto border-b border-life-line bg-life-card px-3 py-1.5"
      data-testid="saved-task-view-tabs"
    >
      {views.map((view) => {
        const isActive = view.id === activeId;
        const isRenaming = renamingId === view.id;
        if (isRenaming) {
          return (
            <input
              key={view.id}
              autoFocus
              aria-label="Rename view"
              value={renameDraft}
              onChange={(event) => setRenameDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") commitRename();
                if (event.key === "Escape") setRenamingId(null);
              }}
              onBlur={commitRename}
              className="shrink-0 rounded-full border border-life-accent bg-white px-2.5 py-1 text-[12.5px] font-medium outline-none"
            />
          );
        }
        const isDropTarget = dragOverId === view.id && dragId !== view.id;
        return (
          <button
            key={view.id}
            type="button"
            draggable
            data-view-id={view.id}
            data-testid={`saved-task-view-tab-${view.id}`}
            onDragStart={(event) => {
              setDragId(view.id);
              event.dataTransfer.setData(DRAG_MIME, String(view.id));
              event.dataTransfer.effectAllowed = "move";
            }}
            onDragOver={(event) => {
              if (dragId === null || dragId === view.id) return;
              event.preventDefault();
              event.dataTransfer.dropEffect = "move";
              setDragOverId(view.id);
            }}
            onDragLeave={() => {
              setDragOverId((curr) => (curr === view.id ? null : curr));
            }}
            onDrop={(event) => {
              event.preventDefault();
              const raw =
                event.dataTransfer.getData(DRAG_MIME)
                || event.dataTransfer.getData("text/plain");
              const src = Number(raw);
              if (Number.isFinite(src) && src !== view.id) {
                moveBefore(src, view.id);
              }
              setDragId(null);
              setDragOverId(null);
            }}
            onDragEnd={() => {
              setDragId(null);
              setDragOverId(null);
            }}
            onClick={(event) => {
              if (isActive) {
                openMenu(view.id, event.currentTarget);
              } else {
                onSelect(view.id);
              }
            }}
            className={cn(
              "flex shrink-0 items-center gap-1 rounded-full border px-2.5 py-1 text-[12.5px] font-medium",
              isActive
                ? "border-transparent bg-life-accent text-white"
                : "border-life-line bg-white text-life-ink-2",
              isDropTarget && "ring-2 ring-life-accent ring-offset-1",
              dragId === view.id && "opacity-50",
            )}
          >
            {view.icon ? (
              <span>{view.icon}</span>
            ) : (
              <span
                className={cn(
                  "inline-flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-semibold",
                  isActive ? "bg-white/20 text-white" : "bg-life-bg text-life-ink-2",
                )}
              >
                {view.name.slice(0, 1).toUpperCase() || "?"}
              </span>
            )}
            <span>{view.name}</span>
            {isActive && dirty ? (
              <span
                className="ml-0.5 h-1.5 w-1.5 rounded-full bg-amber-300"
                aria-label="unsaved"
              />
            ) : null}
            {isActive ? <MoreHorizontal className="ml-0.5 h-3.5 w-3.5 opacity-80" /> : null}
          </button>
        );
      })}
      <button
        type="button"
        onClick={onAdd}
        aria-label="New view"
        className="shrink-0 rounded-full border border-dashed border-life-line bg-white px-2 py-1 text-[12px] text-life-ink-3"
      >
        <Plus className="-mt-0.5 inline h-3 w-3" />
      </button>
      {menuFor !== null && menuAnchor && menuView
        ? createPortal(
            <div
              data-saved-task-view-menu
              style={{
                position: "fixed",
                top: menuAnchor.top,
                left: menuAnchor.left,
                width: MENU_WIDTH,
              }}
              className="z-50 rounded-xl border border-life-line bg-white p-1 text-[13px] shadow-lg"
            >
              <button
                type="button"
                onClick={() => startRename(menuView)}
                className="block w-full rounded-lg px-2 py-1.5 text-left hover:bg-life-bg"
              >
                Rename
              </button>
              <button
                type="button"
                disabled={menuIdx <= 0}
                onClick={() => moveBy(menuView.id, -1)}
                className={cn(
                  "flex w-full items-center gap-1 rounded-lg px-2 py-1.5 text-left",
                  menuIdx <= 0
                    ? "cursor-not-allowed text-life-ink-3"
                    : "hover:bg-life-bg",
                )}
              >
                <ChevronLeft className="h-3.5 w-3.5" /> Move left
              </button>
              <button
                type="button"
                disabled={menuIdx === views.length - 1}
                onClick={() => moveBy(menuView.id, 1)}
                className={cn(
                  "flex w-full items-center gap-1 rounded-lg px-2 py-1.5 text-left",
                  menuIdx === views.length - 1
                    ? "cursor-not-allowed text-life-ink-3"
                    : "hover:bg-life-bg",
                )}
              >
                <ChevronRight className="h-3.5 w-3.5" /> Move right
              </button>
              <button
                type="button"
                onClick={() => {
                  onMakeDefault(menuView.id);
                  setMenuFor(null);
                }}
                className="block w-full rounded-lg px-2 py-1.5 text-left hover:bg-life-bg"
              >
                {menuView.is_default ? "Default view ✓" : "Make default"}
              </button>
              <button
                type="button"
                onClick={() => {
                  onDelete(menuView.id);
                  setMenuFor(null);
                }}
                className="block w-full rounded-lg px-2 py-1.5 text-left text-rose-600 hover:bg-rose-50"
              >
                Delete view
              </button>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
