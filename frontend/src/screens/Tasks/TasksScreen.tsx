import { Filter as FilterIcon, RotateCcw, Save, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Header } from "@/shell/Header";
import { IconPlus } from "@/shell/icons";
import { useIdentity } from "@/shell/identity";
import { cn } from "@/lib/utils";

import { ManageLabelsSheet } from "@/screens/Labels/ManageLabelsSheet";
import { listLabels, type Label } from "@/screens/Labels/labelsApi";

import { FilterSheet } from "./SavedTaskViews/FilterSheet";
import { SavedTaskViewTabs } from "./SavedTaskViews/SavedTaskViewTabs";
import { useSavedTaskViews } from "./SavedTaskViews/useSavedTaskViews";
import type { FilterBlob } from "./savedTaskViewsApi";

import { DoneArchive, doneArchiveFilters } from "./DoneArchive";
import { NewTaskSheet } from "./NewTaskSheet";
import { TaskRow } from "./TaskRow";
import { TaskSearchInput } from "./TaskSearchInput";
import { filterTasksBySearch, tokenize } from "./taskSearch";
import {
  createTask,
  fetchTaskActivity,
  listTasks,
  updateTask,
  type Task,
  type TaskCreate,
} from "./tasksApi";

const ACTIVITY_POLL_MS = 3000;
// "Marked done — Undo" banner lifetime. Long enough to catch a
// fat-fingered check-off, short enough to disappear after a deliberate one.
const UNDO_TOAST_MS = 7000;

function compareUpdatedDesc(a: Task, b: Task): number {
  return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
}

function filterCount(filter: FilterBlob): number {
  let n = 0;
  if (filter.assignee) n += 1;
  if (filter.due) n += 1;
  n += filter.statuses?.length ?? 0;
  n += filter.labels?.length ?? 0;
  return n;
}

export function TasksScreen() {
  const navigate = useNavigate();
  const { assistantName } = useIdentity();
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [composerOpen, setComposerOpen] = useState(false);
  const [labelsOpen, setLabelsOpen] = useState(false);
  const [filterSheetOpen, setFilterSheetOpen] = useState(false);
  const [namePromptOpen, setNamePromptOpen] = useState(false);
  const [newViewName, setNewViewName] = useState("");
  const nameInputRef = useRef<HTMLInputElement>(null);
  const [labels, setLabels] = useState<Label[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeSessionIds, setActiveSessionIds] = useState<Set<number>>(
    () => new Set(),
  );
  const [stalledSessionIds, setStalledSessionIds] = useState<Set<number>>(
    () => new Set(),
  );
  const [erroredSessionIds, setErroredSessionIds] = useState<Set<number>>(
    () => new Set(),
  );
  // Bumped on every task refetch so the lazy Done tail can invalidate
  // its cached page; `doneBump` fires only on a positive check-off so
  // the Done tail can also auto-open and surface the just-completed one.
  const [dataVersion, setDataVersion] = useState(0);
  const [doneBump, setDoneBump] = useState(0);
  const [undoToast, setUndoToast] = useState<
    { taskId: number; title: string } | null
  >(null);
  const undoTimerRef = useRef<number | null>(null);

  const {
    views,
    activeView,
    ready: taskViewsReady,
    workingFilters,
    dirty,
    creating,
    switchView,
    editFilters,
    saveCurrent,
    createFromWorking,
    renameView,
    makeDefault,
    removeView,
    reorderViews,
  } = useSavedTaskViews();

  // Stable key based on the filter blob — refetch tasks whenever the
  // effective filter changes. JSON.stringify is fine: blob is tiny and the
  // single-user app never sees concurrent edits.
  const filterKey = useMemo(() => JSON.stringify(workingFilters), [workingFilters]);

  const refresh = useCallback(async () => {
    if (!taskViewsReady) return;
    try {
      const rows = await listTasks({ ...workingFilters, done: false });
      setTasks(rows);
      setError(null);
      setDataVersion((v) => v + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskViewsReady, filterKey]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    listLabels()
      .then(setLabels)
      .catch(() => setLabels([]));
  }, [labelsOpen]);

  // Poll the runner's active set so the user can see at a glance which
  // tasks the assistant is mid-turn on. Cheap (in-memory on the backend), small
  // payload. Stops while the page is hidden to avoid waste.
  useEffect(() => {
    let cancelled = false;
    let interval: number | null = null;

    const sameMembership = (a: Set<number>, b: Set<number>) =>
      a.size === b.size && [...b].every((v) => a.has(v));

    const tick = async () => {
      try {
        const a = await fetchTaskActivity();
        if (cancelled) return;
        const nextActive = new Set(a.active_session_ids);
        const nextStalled = new Set(a.stalled_session_ids ?? []);
        const nextErrored = new Set(a.errored_session_ids ?? []);
        setActiveSessionIds((prev) =>
          sameMembership(prev, nextActive) ? prev : nextActive,
        );
        setStalledSessionIds((prev) =>
          sameMembership(prev, nextStalled) ? prev : nextStalled,
        );
        setErroredSessionIds((prev) =>
          sameMembership(prev, nextErrored) ? prev : nextErrored,
        );
      } catch {
        // Transient errors are fine — try again on the next tick.
      }
    };

    const start = () => {
      if (interval !== null) return;
      void tick();
      interval = window.setInterval(tick, ACTIVITY_POLL_MS);
    };
    const stop = () => {
      if (interval !== null) {
        window.clearInterval(interval);
        interval = null;
      }
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") start();
      else stop();
    };

    onVisibility();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      cancelled = true;
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  // Apply search on top of the server-side filter blob. Client-side is fine
  // — `tasks` is already the current view's set, and search just narrows it
  // further.
  const visibleTasks = useMemo(
    () => (tasks ? filterTasksBySearch(tasks, searchQuery) : null),
    [tasks, searchQuery],
  );

  const openTasks = useMemo(
    () =>
      visibleTasks
        ? visibleTasks.filter((t) => !t.is_done).sort(compareUpdatedDesc)
        : [],
    [visibleTasks],
  );
  const archiveFilters = useMemo(
    () => doneArchiveFilters(workingFilters),
    [workingFilters],
  );

  const liveCount = useMemo(() => {
    if (!tasks) return 0;
    let n = 0;
    for (const t of tasks) {
      if (activeSessionIds.has(t.chat_session_id) && !t.is_done) {
        n += 1;
      }
    }
    return n;
  }, [tasks, activeSessionIds]);

  const handleCreate = useCallback(
    async (data: TaskCreate) => {
      const created = await createTask(data);
      await refresh();
      navigate(`/tasks/${created.id}`);
    },
    [refresh, navigate],
  );

  const dismissUndo = useCallback(() => {
    if (undoTimerRef.current !== null) {
      window.clearTimeout(undoTimerRef.current);
      undoTimerRef.current = null;
    }
    setUndoToast(null);
  }, []);

  // Bind a fresh 7s window each time the user checks a task off — only on
  // the user-initiated "marked done" path, not on reopens. Reopens never
  // need undo (the user is already recovering); a brand-new banner per
  // checkoff also resets the timer if they spree-complete a few rows.
  const handleAfterToggleDone = useCallback(
    (task: Task, nowDone: boolean) => {
      if (!nowDone) return;
      if (undoTimerRef.current !== null) {
        window.clearTimeout(undoTimerRef.current);
      }
      setUndoToast({ taskId: task.id, title: task.title });
      // Surface the just-completed one: open the Done tail so it's
      // visible at the top (completed_at desc), not silently vanished.
      setDoneBump((v) => v + 1);
      undoTimerRef.current = window.setTimeout(() => {
        setUndoToast(null);
        undoTimerRef.current = null;
      }, UNDO_TOAST_MS);
    },
    [],
  );

  const handleUndo = useCallback(async () => {
    const target = undoToast;
    if (!target) return;
    dismissUndo();
    try {
      await updateTask(target.taskId, { is_done: false });
    } finally {
      void refresh();
    }
  }, [undoToast, dismissUndo, refresh]);

  useEffect(() => {
    return () => {
      if (undoTimerRef.current !== null) {
        window.clearTimeout(undoTimerRef.current);
      }
    };
  }, []);

  const isLive = useCallback(
    (t: Task) => activeSessionIds.has(t.chat_session_id),
    [activeSessionIds],
  );
  const isStalled = useCallback(
    (t: Task) => stalledSessionIds.has(t.chat_session_id),
    [stalledSessionIds],
  );
  const isErrored = useCallback(
    (t: Task) => erroredSessionIds.has(t.chat_session_id),
    [erroredSessionIds],
  );

  function openNamePrompt() {
    setNewViewName("");
    setNamePromptOpen(true);
    setTimeout(() => nameInputRef.current?.focus(), 0);
  }

  async function submitNewView() {
    if (creating) return;
    const name = newViewName.trim();
    if (!name) return;
    await createFromWorking(name, null);
    setNamePromptOpen(false);
  }

  return (
    <div className="flex h-full flex-col">
      <Header
        title="Tasks"
        subtitle={liveCount > 0 ? `${assistantName.toUpperCase()} LIVE · ${liveCount}` : "TASKS"}
        right={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setLabelsOpen(true)}
              className="rounded-full border border-life-line bg-life-card px-3 py-1.5 text-[12px] font-medium text-life-ink-2"
            >
              Labels
            </button>
            <button
              type="button"
              onClick={() => setComposerOpen(true)}
              className="flex items-center gap-1.5 rounded-full bg-life-accent px-3.5 py-2 text-[13px] font-medium text-white"
            >
              <IconPlus />
              New
            </button>
          </div>
        }
      />

      <div className="px-5 pb-2">
        <TaskSearchInput
          value={searchQuery}
          onChange={setSearchQuery}
          width="auto"
        />
      </div>

      {activeView ? (
        <SavedTaskViewTabs
          views={views}
          activeId={activeView.id}
          dirty={dirty}
          onSelect={switchView}
          onRename={renameView}
          onMakeDefault={makeDefault}
          onDelete={removeView}
          onReorder={reorderViews}
          onAdd={openNamePrompt}
        />
      ) : null}

      <div className="flex items-center gap-2 border-b border-life-line bg-life-card px-3 py-1.5">
        <button
          type="button"
          onClick={() => setFilterSheetOpen(true)}
          className="inline-flex items-center gap-1 rounded-full border border-life-line bg-white px-2.5 py-1 text-[12px]"
        >
          <FilterIcon className="h-3 w-3" /> Filters · {filterCount(workingFilters)}
        </button>
        <button
          type="button"
          onClick={saveCurrent}
          disabled={!dirty}
          className={cn(
            "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[12px] font-medium",
            dirty ? "bg-amber-500 text-white" : "bg-life-bg text-life-ink-3",
          )}
        >
          <Save className="h-3 w-3" /> Save view
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-6">
        {tasks === null && !error && (
          <div className="py-10 text-center text-sm text-life-ink-3">
            Loading…
          </div>
        )}
        {error && (
          <div className="py-10 text-center text-sm text-red-500">
            Couldn't load tasks: {error}
          </div>
        )}

        {visibleTasks && (
          <div className="flex flex-col">
            {openTasks.length > 0 ? (
              <div className="flex flex-col divide-y divide-life-line">
                {openTasks.map((task) => (
                  <TaskRow
                    key={task.id}
                    task={task}
                    onOpen={() => navigate(`/tasks/${task.id}`)}
                    onChanged={refresh}
                    onAfterToggleDone={handleAfterToggleDone}
                    isLive={isLive(task)}
                    isStalled={isStalled(task)}
                    isErrored={isErrored(task)}
                    assistantName={assistantName}
                  />
                ))}
              </div>
            ) : (
              <div className="py-10 text-center text-sm text-life-ink-3">
                {tokenize(searchQuery).length > 0
                  ? `No tasks match "${searchQuery.trim()}".`
                  : "No tasks match this view."}
              </div>
            )}
            <DoneArchive
              filters={archiveFilters}
              refreshToken={dataVersion}
              expandToken={doneBump}
              onSelectTask={(task) => navigate(`/tasks/${task.id}`)}
              onChanged={refresh}
              onAfterToggleDone={handleAfterToggleDone}
              isLive={isLive}
              isStalled={isStalled}
              isErrored={isErrored}
              assistantName={assistantName}
            />
          </div>
        )}
      </div>

      <NewTaskSheet
        open={composerOpen}
        onClose={() => setComposerOpen(false)}
        onCreate={handleCreate}
      />

      <ManageLabelsSheet
        open={labelsOpen}
        onClose={() => setLabelsOpen(false)}
      />

      <FilterSheet
        open={filterSheetOpen}
        value={workingFilters}
        labels={labels}
        assistantName={assistantName}
        onChange={editFilters}
        onClose={() => setFilterSheetOpen(false)}
      />

      {undoToast ? (
        <div
          data-testid="task-undo-toast"
          role="status"
          aria-live="polite"
          className="pointer-events-auto fixed inset-x-0 bottom-20 z-30 mx-auto flex w-full max-w-[360px] items-center gap-3 rounded-full border border-life-line bg-life-card px-3 py-2 text-[13px] text-life-ink shadow-lg"
        >
          <span className="min-w-0 flex-1 truncate">
            Marked “{undoToast.title}” done.
          </span>
          <button
            type="button"
            onClick={() => void handleUndo()}
            data-testid="task-undo-button"
            className="inline-flex shrink-0 items-center gap-1 rounded-full bg-life-accent px-3 py-1 text-[12px] font-medium text-white"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Undo
          </button>
          <button
            type="button"
            onClick={dismissUndo}
            aria-label="Dismiss undo"
            className="inline-flex shrink-0 items-center justify-center rounded-full p-1 text-life-ink-3 hover:bg-life-bg"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ) : null}

      {namePromptOpen ? (
        <div
          className="fixed inset-0 z-30 flex items-center justify-center bg-black/40"
          onClick={() => setNamePromptOpen(false)}
        >
          <div
            className="w-[320px] rounded-2xl bg-white p-3 shadow-xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-1 text-[14px] font-semibold">New view</div>
            <div className="mb-2 text-[12px] text-life-ink-3">
              Created from your current filters.
            </div>
            <input
              ref={nameInputRef}
              value={newViewName}
              onChange={(event) => setNewViewName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void submitNewView();
                if (event.key === "Escape") setNamePromptOpen(false);
              }}
              placeholder="View name"
              aria-label="View name"
              className="mb-1 w-full rounded-xl border border-life-line bg-life-bg px-3 py-2 text-[13.5px] outline-none"
            />
            {creating ? (
              <div className="mb-2 text-[11px] text-life-ink-3">
                Picking emoji…
              </div>
            ) : (
              <div className="mb-2 h-[14px]" aria-hidden="true" />
            )}
            <div className="flex justify-end gap-2 text-[12.5px]">
              <button
                type="button"
                onClick={() => setNamePromptOpen(false)}
                className="rounded-full border border-life-line bg-white px-3 py-1.5"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void submitNewView()}
                disabled={creating}
                className={cn(
                  "rounded-full px-3 py-1.5 font-medium text-white",
                  creating ? "bg-life-accent/50" : "bg-life-accent",
                )}
              >
                Create
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
