import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  createView,
  deleteView as deleteViewApi,
  listViews,
  reorderViews as reorderViewsApi,
  type FilterBlob,
  type SavedTaskView,
  type SavedTaskViewCreate,
  updateView,
} from "../savedTaskViewsApi";

// Filter state is mirrored to the URL so the browser back button (and
// shareable links) round-trips correctly when the user dives into a task
// detail and comes back.
const URL_PARAM_KEYS = [
  "view",
  "statuses",
  "assignee",
  "due",
] as const;
type UrlParamKey = (typeof URL_PARAM_KEYS)[number];
const LEGACY_URL_PARAM_KEYS = [...URL_PARAM_KEYS, "group", "labels"] as const;

type ParsedUrl = {
  hasState: boolean;
  viewId: number | null;
  filters: FilterBlob;
};

const STATUS_VALUES = ["open", "scheduled", "waiting"] as const;
type StatusValue = (typeof STATUS_VALUES)[number];

function parseUrl(params: URLSearchParams): ParsedUrl {
  const hasState = URL_PARAM_KEYS.some((k) => params.has(k));
  const viewRaw = params.get("view");
  const viewId = viewRaw && /^\d+$/.test(viewRaw) ? Number(viewRaw) : null;

  const filters: FilterBlob = {};
  const statusesRaw = params.get("statuses");
  if (statusesRaw !== null) {
    const statuses = statusesRaw
      .split(",")
      .filter((s): s is StatusValue =>
        (STATUS_VALUES as readonly string[]).includes(s),
      );
    filters.statuses = statuses;
  }
  const assigneeRaw = params.get("assignee");
  if (assigneeRaw === "user" || assigneeRaw === "assistant") {
    filters.assignee = assigneeRaw;
  } else if (assigneeRaw === "") {
    filters.assignee = null;
  }
  const dueRaw = params.get("due");
  if (dueRaw === "today" || dueRaw === "week") {
    filters.due = dueRaw;
  } else if (dueRaw === "") {
    filters.due = null;
  }

  return { hasState, viewId, filters };
}

function encodeState(
  viewId: number | null,
  filters: FilterBlob,
): Partial<Record<UrlParamKey, string>> {
  const out: Partial<Record<UrlParamKey, string>> = {};
  if (viewId != null) out.view = String(viewId);
  if (filters.statuses !== undefined) {
    out.statuses = filters.statuses.join(",");
  }
  if (filters.assignee !== undefined) out.assignee = filters.assignee ?? "";
  if (filters.due !== undefined) out.due = filters.due ?? "";
  return out;
}

export function useSavedTaskViews() {
  const [searchParams, setSearchParams] = useSearchParams();

  // Read URL once at mount. Subsequent URL writes are driven by state
  // changes; we don't want re-reads to fight the local state.
  const initialUrlRef = useRef<ParsedUrl | null>(null);
  if (initialUrlRef.current === null) {
    initialUrlRef.current = parseUrl(searchParams);
  }
  const initialUrl = initialUrlRef.current;

  const [views, setViews] = useState<SavedTaskView[]>([]);
  const [activeId, setActiveId] = useState<number | null>(initialUrl.viewId);
  const [workingFilters, setWorkingFilters] = useState<FilterBlob>(
    initialUrl.filters,
  );
  const [viewsLoaded, setViewsLoaded] = useState(false);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    listViews().then((rows) => {
      setViews(rows);
      setViewsLoaded(true);
      const fromUrl = initialUrlRef.current;
      const urlView =
        fromUrl?.viewId != null
          ? rows.find((v) => v.id === fromUrl.viewId)
          : undefined;
      const fallback = rows.find((v) => v.is_default) ?? rows[0];
      const target = urlView ?? fallback;
      if (!target) return;
      setActiveId(target.id);
      // If the URL specified a known view but no filter params, hydrate
      // filters from that view. If the URL had explicit overrides, keep
      // them — they represent dirty working state.
      if (!fromUrl?.hasState) {
        setWorkingFilters(target.filters);
      } else if (urlView && fromUrl.viewId === urlView.id) {
        const hasOverride =
          fromUrl.filters.statuses !== undefined ||
          fromUrl.filters.assignee !== undefined ||
          fromUrl.filters.due !== undefined;
        if (!hasOverride) setWorkingFilters(target.filters);
      }
    });
  }, []);

  const activeView = useMemo(
    () => views.find((v) => v.id === activeId) ?? null,
    [views, activeId],
  );

  const dirty = useMemo(() => {
    if (!activeView) return false;
    return JSON.stringify(activeView.filters) !== JSON.stringify(workingFilters);
  }, [activeView, workingFilters]);

  // Mirror working state to the URL after views have loaded. `replace`
  // avoids polluting browser history with a new entry per keystroke.
  useEffect(() => {
    if (!viewsLoaded) return;
    const encoded = encodeState(activeId, workingFilters);
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const key of LEGACY_URL_PARAM_KEYS) next.delete(key);
        for (const [key, value] of Object.entries(encoded)) {
          next.set(key, value);
        }
        return next;
      },
      { replace: true },
    );
  }, [viewsLoaded, activeId, workingFilters, setSearchParams]);

  const switchView = useCallback(
    (id: number) => {
      const view = views.find((v) => v.id === id);
      if (!view) return;
      setActiveId(id);
      setWorkingFilters(view.filters);
    },
    [views],
  );

  const editFilters = useCallback((patch: FilterBlob) => {
    setWorkingFilters((curr) => ({ ...curr, ...patch }));
  }, []);

  const saveCurrent = useCallback(async () => {
    if (!activeView || !dirty) return;
    const updated = await updateView(activeView.id, {
      filters: workingFilters,
      group_by: "none",
    });
    setViews((curr) => curr.map((v) => (v.id === updated.id ? updated : v)));
  }, [activeView, dirty, workingFilters]);

  const createFromWorking = useCallback(
    async (name: string, icon: string | null) => {
      const body: SavedTaskViewCreate = {
        name,
        icon,
        filters: workingFilters,
        group_by: "none",
      };
      setCreating(true);
      try {
        const created = await createView(body);
        setViews((curr) => [...curr, created]);
        setActiveId(created.id);
        return created;
      } finally {
        setCreating(false);
      }
    },
    [workingFilters],
  );

  const renameView = useCallback(async (id: number, name: string) => {
    const updated = await updateView(id, { name });
    setViews((curr) => curr.map((v) => (v.id === id ? updated : v)));
  }, []);

  const makeDefault = useCallback(async (id: number) => {
    const updated = await updateView(id, { is_default: true });
    setViews((curr) => curr.map((v) => ({ ...v, is_default: v.id === updated.id })));
  }, []);

  const removeView = useCallback(
    async (id: number) => {
      await deleteViewApi(id);
      setViews((curr) => curr.filter((v) => v.id !== id));
      if (activeId === id) {
        const fallback = views.find((v) => v.id !== id);
        if (fallback) switchView(fallback.id);
      }
    },
    [activeId, switchView, views],
  );

  const reorderViews = useCallback(
    async (orderedIds: number[]) => {
      // Optimistic reorder so the tabs reflow before the round-trip
      // resolves. The server is the source of truth, so we still apply
      // its result over the optimistic state once it returns.
      setViews((curr) => {
        const byId = new Map(curr.map((v) => [v.id, v]));
        const next = orderedIds
          .map((id, idx) => {
            const view = byId.get(id);
            return view ? { ...view, sort_index: idx } : null;
          })
          .filter((v): v is SavedTaskView => v !== null);
        // Preserve any tabs the caller didn't include (shouldn't happen
        // in normal use, but keeps the UI honest if the lists drift).
        const seen = new Set(orderedIds);
        for (const v of curr) if (!seen.has(v.id)) next.push(v);
        return next;
      });
      const updated = await reorderViewsApi(orderedIds);
      setViews((curr) => {
        const updatedById = new Map(updated.map((v) => [v.id, v]));
        return curr.map((v) => updatedById.get(v.id) ?? v);
      });
    },
    [],
  );

  const discardWorking = useCallback(() => {
    if (!activeView) return;
    setWorkingFilters(activeView.filters);
  }, [activeView]);

  return {
    views,
    activeView: activeView!,
    ready: viewsLoaded,
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
    discardWorking,
  };
}
