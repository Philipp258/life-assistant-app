import type { Meta, StoryObj } from "@storybook/react-vite";
import { Filter as FilterIcon, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { MemoryRouter } from "react-router-dom";

import { Header } from "@/shell/Header";
import { IconPlus } from "@/shell/icons";

import { SavedTaskViewTabs } from "./SavedTaskViews/SavedTaskViewTabs";
import { TaskRow } from "./TaskRow";
import { TaskSearchInput } from "./TaskSearchInput";
import { filterTasksBySearch } from "./taskSearch";
import type { SavedTaskView } from "./savedTaskViewsApi";
import type { Task } from "./tasksApi";

/**
 * Storybook prototypes for task search. Each story renders a mock Tasks
 * screen with realistic rows — including completed and filter-hidden ones —
 * so the user can judge each placement/interaction option in context.
 *
 * Variants:
 *   - A: Toolbar inline — search input lives in the filter toolbar.
 *   - B: Header expandable — icon button next to "New" toggles an input.
 *   - C: Below-title — full-width search bar between title and tabs;
 *        this is the shipped production placement.
 *   - D: Scope toggle — toolbar input with a "Current view / All tasks"
 *        scope toggle, useful when you've completed a task and the
 *        current view hides it.
 */

function makeTask(overrides: Partial<Task>): Task {
  return {
    id: 0,
    title: "Untitled",
    description: null,
    is_done: false,
    assignee: "user",
    chat_session_id: 0,
    goal_id: null,
    goal_title: null,
    do_at: null,
    due_at: null,
    interval_unit: null,
    interval_count: null,
    created_at: "2026-05-01T10:00:00Z",
    updated_at: "2026-05-06T10:00:00Z",
    completed_at: null,
    state: "yours",
    kind: "todo",
    source_chat_session_id: null,
    source_chat_title: null,
    ...overrides,
  };
}

// Realistic mix: working, scheduled, done, mine + assistant, with varied
// descriptions so search has something to find.
const CURRENT_VIEW: Task[] = [
  makeTask({
    id: 1,
    title: "Reply to Anna about the venue",
    description: "She asked about catering options for the dinner.",
  }),
  makeTask({
    id: 2,
    title: "Pick groceries on the way home",
    description: "Milk, eggs, bread, apples.",
  }),
  makeTask({
    id: 3,
    title: "File quarterly taxes",
    description: "April deadline. Need the W-2 from work.",
    due_at: "2099-04-15T00:00:00Z",
    kind: "deadline",
  }),
  makeTask({
    id: 4,
    title: "Call dentist tomorrow morning",
    do_at: "2099-05-08T09:00:00Z",
    kind: "scheduled-todo",
  }),
  makeTask({
    id: 5,
    title: "Finish slide deck",
    description: "Pitch deck for the Q3 review.",
    is_done: true,
    completed_at: "2026-05-06T14:00:00Z",
  }),
  makeTask({
    id: 6,
    title: "Summarise unread newsletters",
    assignee: "assistant",
    chat_session_id: 100,
    kind: "job",
    state: "running",
  }),
  makeTask({
    id: 7,
    title: "Daily standup digest",
    assignee: "assistant",
    interval_unit: "day",
    interval_count: 1,
    kind: "routine",
    state: "running",
  }),
];

// Extra tasks that aren't in the current view — used by the "scope toggle"
// variant to demo searching beyond the current filter.
const OTHER_TASKS: Task[] = [
  makeTask({
    id: 50,
    title: "Book flights to Anna's wedding",
    description: "Probably from BER. Budget around 400 EUR.",
    is_done: true,
    completed_at: "2026-04-12T20:00:00Z",
  }),
  makeTask({
    id: 51,
    title: "Cancel old gym membership",
    is_done: true,
    completed_at: "2026-04-01T10:00:00Z",
  }),
  makeTask({
    id: 52,
    title: "Plan summer trip to Lisbon",
    description: "Anna wants to come too.",
  }),
];

const ALL_TASKS = [...CURRENT_VIEW, ...OTHER_TASKS];

const MOCK_VIEWS: SavedTaskView[] = [
  {
    id: 1,
    name: "Inbox",
    icon: "📥",
    filters: {},
    group_by: "none",
    sort_index: 0,
    is_default: true,
  },
  {
    id: 2,
    name: "Mine",
    icon: null,
    filters: { assignee: "user" },
    group_by: "none",
    sort_index: 1,
    is_default: false,
  },
  {
    id: 3,
    name: "Assistant",
    icon: null,
    filters: { assignee: "assistant" },
    group_by: "none",
    sort_index: 2,
    is_default: false,
  },
];

type FrameProps = {
  toolbar?: React.ReactNode;
  belowTitle?: React.ReactNode;
  right?: React.ReactNode;
  results: Task[];
  query: string;
  scopeNote?: string;
};

/** Mini Tasks-screen shell used by every variant story. */
function Frame({ toolbar, belowTitle, right, results, query, scopeNote }: FrameProps) {
  const [activeViewId, setActiveViewId] = useState(1);
  const rows = useMemo(() => results.filter((task) => !task.is_done), [results]);
  const noResults = query.trim() !== "" && rows.length === 0;

  return (
    <MemoryRouter>
      <div className="mx-auto flex h-[640px] w-full max-w-md flex-col overflow-hidden rounded-2xl border border-life-line bg-life-bg">
        <Header
          title="Tasks"
          subtitle="TASKS"
          right={
            right ?? (
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="flex items-center gap-1.5 rounded-full bg-life-accent px-3.5 py-2 text-[13px] font-medium text-white"
                >
                  <IconPlus />
                  New
                </button>
              </div>
            )
          }
        />

        {belowTitle}

        <SavedTaskViewTabs
          views={MOCK_VIEWS}
          activeId={activeViewId}
          dirty={false}
          onSelect={setActiveViewId}
          onRename={() => undefined}
          onMakeDefault={() => undefined}
          onDelete={() => undefined}
          onReorder={() => undefined}
          onAdd={() => undefined}
        />

        {toolbar ?? (
          <div className="flex items-center gap-2 border-b border-life-line bg-life-card px-3 py-1.5">
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-full border border-life-line bg-white px-2.5 py-1 text-[12px]"
            >
              <FilterIcon className="h-3 w-3" /> Filters · 0
            </button>
          </div>
        )}

        {scopeNote && (
          <div className="border-b border-life-line bg-life-bg px-3 py-1 text-[11px] text-life-ink-3">
            {scopeNote}
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-5 pb-6">
          {noResults ? (
            <div className="py-10 text-center text-sm text-life-ink-3">
              No tasks match “{query}”.
            </div>
          ) : (
            <div className="flex flex-col divide-y divide-life-line">
              {rows.map((task) => (
                <TaskRow
                  key={task.id}
                  task={task}
                  onOpen={() => undefined}
                  assistantName="Assistant"
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </MemoryRouter>
  );
}

const meta = {
  title: "Tasks/TaskSearch",
  parameters: {
    layout: "centered",
    docs: {
      description: {
        component:
          "Search affordance prototypes for the Tasks screen. Each variant filters realistic task rows so the interaction can be judged in context. The shipped production placement is **C — Below-title persistent**. Search remains local UI state: it narrows the active view results but is not saved into task views.",
      },
    },
  },
} satisfies Meta;

export default meta;
type Story = StoryObj<typeof meta>;

/** A — Toolbar inline. Search input lives in the existing filter toolbar
 * alongside Filters / group-by. Always visible, zero clicks to start typing,
 * but uses some horizontal space on narrow widths.
 *
 * Tradeoff: compact vertically, but makes the toolbar busier than the shipped
 * below-title placement. */
export const A_ToolbarInline: Story = {
  render: () => {
    const [q, setQ] = useState("");
    const results = useMemo(() => filterTasksBySearch(CURRENT_VIEW, q), [q]);
    return (
      <Frame
        query={q}
        results={results}
        toolbar={
          <div className="flex items-center gap-2 border-b border-life-line bg-life-card px-3 py-1.5">
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-full border border-life-line bg-white px-2.5 py-1 text-[12px]"
            >
              <FilterIcon className="h-3 w-3" /> Filters · 0
            </button>
            <TaskSearchInput value={q} onChange={setQ} width="sm" />
          </div>
        }
      />
    );
  },
};

/** B — Header expandable. A search icon next to "New" expands to a full-
 * width input below the header. Saves space when not searching, but takes a
 * click to start typing and adds a row when active. */
export const B_HeaderExpandable: Story = {
  render: () => {
    const [open, setOpen] = useState(false);
    const [q, setQ] = useState("");
    const results = useMemo(() => filterTasksBySearch(CURRENT_VIEW, q), [q]);
    return (
      <Frame
        query={q}
        results={results}
        right={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              aria-pressed={open}
              aria-label="Search tasks"
              className="flex h-8 w-8 items-center justify-center rounded-full border border-life-line bg-life-card text-life-ink-2"
            >
              <Search className="h-4 w-4" />
            </button>
            <button
              type="button"
              className="flex items-center gap-1.5 rounded-full bg-life-accent px-3.5 py-2 text-[13px] font-medium text-white"
            >
              <IconPlus />
              New
            </button>
          </div>
        }
        belowTitle={
          open ? (
            <div className="border-b border-life-line bg-life-card px-3 py-1.5">
              <TaskSearchInput
                value={q}
                onChange={setQ}
                width="auto"
                autoFocus
                onEscapeWhenEmpty={() => setOpen(false)}
              />
            </div>
          ) : null
        }
      />
    );
  },
};

/** C — Below-title persistent. A full-width search bar between the page
 * title and the saved-view tabs. This is the shipped production placement:
 * visible without a click, enough width for natural queries, and the toolbar
 * stays focused on view/filter controls. Search is local-only and is
 * applied on top of the active view result set. */
export const C_BelowTitle: Story = {
  render: () => {
    const [q, setQ] = useState("");
    const results = useMemo(() => filterTasksBySearch(CURRENT_VIEW, q), [q]);
    return (
      <Frame
        query={q}
        results={results}
        belowTitle={
          <div className="px-5 pb-2">
            <TaskSearchInput value={q} onChange={setQ} width="auto" />
          </div>
        }
      />
    );
  },
};

/** D — Scope toggle. Variant A plus a scope chip that flips between
 * "Current view" (default; filters the already-visible task set) and
 * "All tasks" (also searches done/hidden-by-filter rows). Directly
 * addresses the "I accidentally checked it off and now can't find it"
 * case. More machinery but explicit about scope. */
export const D_ScopeToggle: Story = {
  render: () => {
    const [q, setQ] = useState("");
    const [scope, setScope] = useState<"current" | "all">("current");
    const source = scope === "current" ? CURRENT_VIEW : ALL_TASKS;
    const results = useMemo(() => filterTasksBySearch(source, q), [source, q]);
    const querying = q.trim() !== "";
    return (
      <Frame
        query={q}
        results={results}
        toolbar={
          <div className="flex items-center gap-2 border-b border-life-line bg-life-card px-3 py-1.5">
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-full border border-life-line bg-white px-2.5 py-1 text-[12px]"
            >
              <FilterIcon className="h-3 w-3" /> Filters · 0
            </button>
            <TaskSearchInput value={q} onChange={setQ} width="sm" />
            {querying && (
              <button
                type="button"
                onClick={() => setScope((s) => (s === "current" ? "all" : "current"))}
                className="inline-flex items-center gap-1 rounded-full border border-life-line bg-white px-2 py-0.5 text-[11px] text-life-ink-2"
                aria-pressed={scope === "all"}
              >
                {scope === "current" ? "Current view" : "All tasks"}
              </button>
            )}
          </div>
        }
        scopeNote={
          querying
            ? scope === "current"
              ? "Searching the current view. Switch scope to include filtered-out and other tasks."
              : "Searching all tasks (including hidden by filters)."
            : undefined
        }
      />
    );
  },
};

/** Empty-state preview for any variant. Use this to judge how a no-results
 * message reads when the user mistypes. */
export const EmptyResults: Story = {
  render: () => (
    <Frame
      query="zzz-no-match"
      results={[]}
      toolbar={
        <div className="flex items-center gap-2 border-b border-life-line bg-life-card px-3 py-1.5">
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-full border border-life-line bg-white px-2.5 py-1 text-[12px]"
          >
            <FilterIcon className="h-3 w-3" /> Filters · 0
          </button>
          <TaskSearchInput value="zzz-no-match" onChange={() => undefined} width="sm" />
        </div>
      }
    />
  ),
};

/** Standalone input — useful for tweaking input chrome without the rest of
 * the screen. */
export const InputOnly: Story = {
  render: () => {
    const [q, setQ] = useState("");
    return (
      <div className="w-[320px] p-4">
        <TaskSearchInput value={q} onChange={setQ} />
      </div>
    );
  },
};

/** Row-level demo: a single TaskRow next to the search box to sanity-check
 * spacing of the input against the surrounding row chrome. */
export const RowAlignmentCheck: Story = {
  render: () => {
    const [q, setQ] = useState("");
    return (
      <MemoryRouter>
        <div className="w-[420px] space-y-3 p-4">
          <TaskSearchInput value={q} onChange={setQ} />
          <div className="rounded-xl border border-life-line bg-white">
            <TaskRow task={CURRENT_VIEW[0]} onOpen={() => undefined} />
          </div>
        </div>
      </MemoryRouter>
    );
  },
};
