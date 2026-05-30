import { Archive, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

import { TaskRow } from "./TaskRow";
import {
  listDoneTasks as listDoneTasksApi,
  type DonePage,
  type ListTasksParams,
  type Task,
} from "./tasksApi";

type ArchiveFilters = Omit<ListTasksParams, "done" | "statuses">;

export type DoneArchiveProps = {
  filters?: ArchiveFilters;
  refreshToken?: number;
  expandToken?: number;
  onSelectTask: (task: Task) => void;
  onChanged: () => void;
  onAfterToggleDone?: (task: Task, nowDone: boolean) => void;
  isLive: (task: Task) => boolean;
  isStalled: (task: Task) => boolean;
  isErrored: (task: Task) => boolean;
  assistantName: string;
  fetchDonePage?: (params: ArchiveFilters, cursor: string | null) => Promise<DonePage>;
};

export function doneArchiveFilters(filters: ListTasksParams): ArchiveFilters {
  return {
    assignee: filters.assignee,
    due: filters.due,
  };
}

export function DoneArchive({
  filters = {},
  refreshToken = 0,
  expandToken = 0,
  onSelectTask,
  onChanged,
  onAfterToggleDone,
  isLive,
  isStalled,
  isErrored,
  assistantName,
  fetchDonePage,
}: DoneArchiveProps) {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<Task[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loadedOnce, setLoadedOnce] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadMore = useCallback(async () => {
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      const page = fetchDonePage
        ? await fetchDonePage(filters, cursor)
        : await listDoneTasksApi(filters, cursor);
      setRows((prev) => [...prev, ...page.tasks]);
      setCursor(page.nextCursor);
      setLoadedOnce(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [cursor, fetchDonePage, filters, loading]);

  useEffect(() => {
    if (open && !loadedOnce && !loading) void loadMore();
  }, [open, loadedOnce, loading, loadMore]);

  const firstRefresh = useRef(true);
  useEffect(() => {
    if (firstRefresh.current) {
      firstRefresh.current = false;
      return;
    }
    setRows([]);
    setCursor(null);
    setLoadedOnce(false);
    setError(null);
  }, [refreshToken, filters]);

  const firstExpand = useRef(true);
  useEffect(() => {
    if (firstExpand.current) {
      firstExpand.current = false;
      return;
    }
    setOpen(true);
  }, [expandToken]);

  const countLabel =
    loadedOnce && cursor === null ? String(rows.length) : loadedOnce ? `${rows.length}+` : null;

  return (
    <section className="border-t border-life-line bg-life-card/60" aria-label="Done archive">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-[13px] text-life-ink-2 hover:bg-life-card"
      >
        <Archive className="h-4 w-4 text-life-ink-3" />
        <span className="min-w-0 flex-1 font-medium">Done archive</span>
        {countLabel ? (
          <span className="rounded-full bg-life-line/70 px-2 py-0.5 text-[11px] font-medium text-life-ink-3">
            {countLabel}
          </span>
        ) : null}
        <ChevronRight
          className={cn(
            "h-4 w-4 text-life-ink-3 transition-transform",
            open && "rotate-90",
          )}
        />
      </button>

      {open ? (
        <div className="border-t border-life-line">
          <div className="flex flex-col divide-y divide-life-line">
            {rows.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                onOpen={() => onSelectTask(task)}
                onChanged={onChanged}
                onAfterToggleDone={onAfterToggleDone}
                isLive={isLive(task)}
                isStalled={isStalled(task)}
                isErrored={isErrored(task)}
                assistantName={assistantName}
              />
            ))}
          </div>
          {loading ? (
            <div className="px-3 py-2.5 text-[12px] text-life-ink-3">Loading...</div>
          ) : null}
          {error ? (
            <button
              type="button"
              onClick={() => void loadMore()}
              className="w-full px-3 py-2.5 text-left text-[12px] text-red-500"
            >
              Couldn't load done tasks. Retry
            </button>
          ) : null}
          {!loading && !error && loadedOnce && rows.length === 0 ? (
            <div className="px-3 py-2.5 text-[12px] text-life-ink-3">
              Nothing done in this view yet.
            </div>
          ) : null}
          {!loading && !error && cursor !== null ? (
            <button
              type="button"
              onClick={() => void loadMore()}
              className="w-full px-3 py-2.5 text-left text-[12px] font-medium text-life-ink-3 hover:text-life-ink-2"
            >
              Show older...
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
