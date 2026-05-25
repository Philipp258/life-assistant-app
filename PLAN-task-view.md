# Task view redesign — implementation plan

Decided model: **two-axis list**. Outer grouping is user-picked
(`assignee` default, also `none` / `label`). Inner is fixed per outer
group: **Now → Waiting → Scheduled (collapsibles) → Done (collapsed,
paginated tail)**. "Status" stops being an outer grouping; scheduled /
waiting / now are properties of an open task. Done is always a terminal
collapsed tail, never sorted among open tasks.

Sort: open by **last-activity desc** (`max(task.updated_at, last
non-archived message)`), done by **completed_at desc**.

## Sequencing

Structure first (cheap, ~80% of the pain), scale as a fast-follow,
detail polish last. Each phase is independently shippable on the current
branch.

---

## Phase 1 — Two-axis structure (frontend-led)

Goal: kill the "lost task / giant flat list / can't navigate" pain.
No pagination yet — Done tail renders all done rows (still collapsed).

### Backend

- `backend/app/tasks/service.py`
  - Refactor the last-message subquery out of `list_tasks_with_activity`
    (`service.py:106-144`) into `_last_msg_subq(session)` so both it and
    `list_tasks` share one definition (DRY; don't touch the reflection
    caller's contract — see interaction map).
  - `list_tasks` (`service.py:65-103`): for **open** tasks, ORDER BY
    computed activity desc, then `id desc`. Keep current ORDER BY only
    for the done slice (until Phase 2 it still returns done inline).
    Add `done: bool | None` param: `None` = current behaviour,
    `False` = open only, `True` = done only.
- `backend/app/tasks/router.py` (`60-75`): add `done: bool | None`
  query param. Keep `status` accepted but ignored (back-compat;
  comment it as deprecated). Response envelope unchanged this phase
  (`{"tasks": [...]}`).

### Frontend

- `savedTaskViewsApi.ts:8` — `GroupBy` becomes
  `"none" | "assignee" | "label"` (drop `"status"`). Default `"assignee"`.
- `useSavedTaskViews` — coerce legacy persisted `group_by === "status"`
  → `"assignee"` on read (belt; the backend data migration below is the
  suspenders).
- `FilterBlob` (`savedTaskViewsApi.ts:1-6`) — drop `statuses`. Leftover
  `statuses` keys in stored `filters_json` deserialize harmlessly
  (dict is permissive) and are no longer sent.
- `FilterSheet.tsx:109-121` — remove the 4 status chips. Keep
  owner/labels/due. (Per filter-UI memory: live-apply, single save
  outside sheet — unchanged pattern.)
- `tasksApi.ts:65-77` — drop `status` from `ListTasksParams`/query; add
  `done?: boolean`.
- **New** `frontend/src/screens/Tasks/TwoAxisList.tsx` — production
  component generalised from the Storybook sketch
  (`TwoAxisTaskList.stories.tsx`). Props: `tasks: Task[]`,
  `outer: "none" | "assignee" | "label"`, owner/assistant name,
  activity flags, `onOpen`, `onChanged`, `onAfterToggleDone`. Renders:
  outer groups (collapsible headers, owner = Mine / Assistant; label =
  per-slug + "No label"; none = single implicit group) → inner
  tri-tier using the **real** `TaskRow` (`TaskRow.tsx`): Now (flat,
  activity order) · Waiting (collapsible, default open) · Scheduled
  (collapsible, default open) · Done (collapsible, default closed).
  Open/sub-state classification reuses `taxonomy.ts` `groupOf` mapped to
  {now,waiting,scheduled}; done filtered to the tail.
- **New** `useCollapseState(key)` hook — persists collapse per
  `outerKey:section` in `localStorage` (`tasks.collapse.v1`). Done
  still auto-opens when something completed <24h
  (`wasRecentlyCompleted`, `format.ts:72`) **unless** the user has an
  explicit stored toggle for that key.
- `TasksScreen.tsx` — delete the `groupBy === "status"` branch
  (`440-441`) and `FlatOrGroupedList` (`588-684`); route all grouping
  through `TwoAxisList`. Remove the `status` option from the group-by
  `<select>` (`338-343`). Keep the undo toast as-is (7s,
  `UNDO_TOAST_MS`, `277-309`) — short toast + always-reachable Done
  tail is the agreed recovery model. Owner-vs-assignee-filter conflict:
  when `assignee` filter is set, only that owner group renders (filter
  wins; no empty peer group).
- Update `TwoAxisTaskList.stories.tsx` to import the real `TwoAxisList`
  (replace the inert sketch rows) so the sketch becomes the live
  Storybook record.

### Migration

- `backend/alembic/versions/<rev>_coerce_status_groupby.py`
  (down_revision = `f8a16b3092c5`, single head). Data-only:
  `UPDATE saved_task_views SET group_by='assignee' WHERE
  group_by='status'`. House style: `op.batch_alter_table` not needed
  (plain UPDATE); follow header/`upgrade`/`downgrade` shape of
  `f8a16b3092c5_add_message_source_session_id.py`. `downgrade` = no-op
  (irreversible coercion; document why).

### Tests — Phase 1

- `backend/tests/test_tasks_api.py` (existing harness: `client`
  fixture, POST-then-assert):
  - `test_open_sorted_by_last_activity` — 3 tasks; post a message into
    one's chat session; assert that task sorts first among open.
  - `test_list_done_param_splits` — `?done=false` excludes done;
    `?done=true` returns only done; no param = legacy all.
  - `test_legacy_status_param_ignored` — `?status=open` returns same as
    no status (back-compat, no 422).
  - `test_recurring_spawn_lands_open_in_activity_order` — complete a
    recurring task; spawned next instance appears in `?done=false`.
- `backend/tests/test_migrations.py` (or inline) —
  `test_status_groupby_coerced`: seed a `saved_task_views` row with
  `group_by='status'`, run upgrade, assert `'assignee'`.
- `frontend/src/screens/Tasks/TwoAxisList.test.tsx` (vitest, colocate,
  MemoryRouter + `vi.mock` per `TasksScreen.test.tsx` pattern):
  - renders Mine/Assistant outer groups with tri-tier inner;
  - Done section collapsed by default, expands on click;
  - collapse state persists across remount (localStorage);
  - Done auto-opens when a task completed <24h.
- `frontend/src/screens/Tasks/TasksScreen.test.tsx` — extend:
  legacy saved view `group_by:"status"` renders as assignee grouping
  (coercion); group-by `<select>` has no "status" option.

---

## Phase 2 — Done archive at scale

Goal: thousands of done tasks without rendering them all. Only the Done
tail is paginated; open list stays unbounded-but-bounded.

### Backend

- Migration `<rev>_index_done_completed.py` — composite index
  `ix_tasks_done_completed (is_done, completed_at, id)` via
  `op.batch_alter_table("tasks")` (SQLite batch, `render_as_batch`).
  Hand-written (perf-only index; autogenerate unreliable here).
- `service.py` — `list_done_tasks(session, *, assignee, labels,
  cursor, limit)` keyset pagination: `WHERE is_done` + filters,
  `ORDER BY completed_at DESC, id DESC`, `(completed_at,id) < cursor`,
  `LIMIT limit+1` to compute `next_cursor`.
- `schemas.py` — done list envelope `{"tasks":[...],
  "next_cursor": str | None}` (cursor = opaque base64 of
  `completed_at|id`). Open endpoint envelope unchanged.
- `router.py` — `GET /api/tasks?done=true&cursor=&limit=` returns the
  paginated envelope; `done=false`/absent unchanged.

### Frontend

- `tasksApi.ts` — `listDoneTasks(params, cursor?) →
  {tasks, nextCursor}`.
- `TwoAxisList.tsx` — Done tail: lazy-fetch first page when expanded,
  "Show older (N more)" button loads next cursor page; virtualise the
  expanded list (windowing) once it exceeds a threshold (e.g.
  react-virtual or a minimal manual window — evaluate; prefer a small
  dependency-free windowing util to avoid new deps unless one already
  vendored). Per-owner-group Done tails fetch independently with that
  group's `assignee`.

### Tests — Phase 2

- `backend/tests/test_tasks_api.py`:
  - `test_done_pagination_first_page_and_cursor` — 5 done, `limit=2`,
    walk cursor to exhaustion, assert stable `completed_at desc, id
    desc` order and `next_cursor` null at end.
  - `test_done_pagination_respects_filters` — assignee + label filters
    apply within the done page.
  - `test_done_cursor_opaque_and_tamper_safe` — malformed cursor →
    422, not 500.
- `frontend/.../TwoAxisList.test.tsx` — "Show older" fetches next page
  and appends; Done not fetched until expanded.

---

## Phase 3 — Detail-page polish

- `TaskDetailPage.tsx` `CompactTaskHeader` (`305-481`): title on its
  own row (`font-serif text-[22px]`, full width, no `truncate`
  competing with buttons); action buttons move to a second row below
  (`flex flex-wrap gap-1.5`). Removes the cramped-title bug.
- Rename **Pause → "Take over"** (`CompactTaskHeader` button,
  `data-testid="task-pause"`; handler `togglePause`
  `TaskDetailPage.tsx:338-340` unchanged — still `onPatch({assignee:
  "user"})`). Add a help/tooltip: hands control back to you; an
  in-flight turn finishes before the assistant lets go. Keep "Run now"
  separate (`handleRunNow`, `120-124`).
- Mobile description editor: **new** `DescriptionEditor` presented
  full-screen (bottom `Sheet`, `h-[100dvh]` on mobile / large modal on
  desktop). `EditTaskSheet.tsx:222-236` — replace inline `Textarea`
  with an "Edit description" row that opens `DescriptionEditor`; commit
  via the same `description` patch on save. Edit sheet becomes
  metadata-only → uncramped on mobile.

### Tests — Phase 3

- `frontend/src/screens/Tasks/TaskDetailPage.test.tsx`:
  - title renders on its own row (assert layout/testid, not pixels);
  - "Take over" button present on assistant-running task, calls patch
    `{assignee:"user"}`;
  - "Run now" still present/independent.
- `frontend/src/screens/Tasks/DescriptionEditor.test.tsx` — opens
  full-screen, edits, saves → patch fired with new description; cancel
  → no patch.

---

## Phase 4 — Labels quick-add (optional, low priority)

- Quick-add affordance: a "＋ label" chip on the detail metadata row
  (and optionally hover on `TaskRow`) opening the existing label
  picker, so adding a label doesn't require opening the full Edit
  sheet. Reuses label assign API (`PATCH /api/tasks/{id}
  {labels:[...]}`). No backend change.
- Test: `frontend/.../*.test.tsx` — quick-add attaches a label via
  patch without opening EditTaskSheet.

---

## Cross-feature interaction map

- **Reflection agent** (`backend/app/agent/tools/tasks.py`) is the only
  caller of `list_tasks_with_activity`. Phase 1 refactor extracts the
  shared subquery but **must not change that function's signature or
  ordering** — verify its test still passes; add a regression assert if
  none exists.
- **Recurring spawn** (`service.py:331-358`) copies title, description,
  assignee, interval, labels; lands `is_done=False`, fresh chat
  session, `completed_at=None`. With future `do_at` it classifies as
  **Scheduled** in the inner tri-tier; if `do_at` already passed it
  falls to **Now**. No code change needed — covered by the spawn test.
- **Saved task views** persist server-side (`saved_task_views`,
  `filters_json` + `group_by`). Removing `statuses`/`status` group:
  data migration coerces `group_by`; stray `statuses` in `filters_json`
  is inert. Delete-last-view guard (`router.py`) unaffected.
- **Runner activity poll** (`isLive/isStalled/isErrored`) still feeds
  the **Waiting** sub-state classification (`taxonomy.groupOf` +
  signal). Unchanged contract; `TwoAxisList` passes the same flags
  `TaskGroupsView` did.
- **Run-now / Take-over**: list-row quick actions
  (`RowQuickActions`, `TaskRow.tsx:224-274`) and detail header share
  the assign/run semantics; rename is label-only, no behaviour change.
- **Undo toast** stays the transient recovery path; the always-present
  collapsed Done tail + <24h auto-expand is the durable one. No
  pin-in-open-list (keeps the open list pure — agreed trade).

## Open knobs (defaults chosen, flag if you disagree)

- Undo toast duration: keep **7s** (not lengthened — Done tail covers
  the rest).
- Done auto-expand window: keep **24h** (`format.ts` constant).
- Waiting/Scheduled collapsibles: **default open**; Done **default
  closed**. Persisted per outer group.
- Virtualization lib: prefer dependency-free windowing; revisit if a
  windowing dep is already vendored.

## Out of scope / explicitly not doing

- No "pin just-completed task at top of open list" (rejected: dirties
  the open list).
- No new task sub-steps / no Run button (per existing product
  constraints).
- No commits/branches as part of planning — work stacks on the current
  branch; only task files staged, WIP left in place.

---

# Round 2 — UI polish (from live dogfooding 2026-05-17)

Five issues from testing the seeded UI. Root causes:

| # | Report | Root cause |
|---|--------|------------|
| 1 | Tasks should be two rows | `TaskRow` is one line; title competes with labels/meta/actions |
| 2 | Two collapsibles not distinct | `OuterSection` header (text-[13px]/600/ink-2) vs inner `SectionHeader` (text-[11px] uppercase/ink-3) too similar; no indent, no rule, same caret |
| 3 | Keep the check box? | Resolved: keep. No change. |
| 4 | "Sign button" — empty space, only on hover | `RowQuickActions` + caret are `opacity-0 group-hover:opacity-100`; reserved width reads as a mystery gap, invisible on touch |
| 5 | Titles cut off / unreadable | `min-w-0 truncate` single-line title, squeezed by the same row's chips + RightLabel + actions |

1, 4, 5 are one job: redesign `TaskRow` into two lines. 2 is a
`TwoAxisList` hierarchy job. `TaskRow` is shared by the status path
(`TaskGroupsView`) too — the redesign improves both (intended, flagged).

## A. `TaskRow` two-line redesign — `frontend/src/screens/Tasks/TaskRow.tsx`

Layout (`items-start`, not center):

```
[ ☐ ]  [ avatar ]  ┌ line 1: TITLE — up to 2 lines, no truncate ──────┐  [ action ]
                    └ line 2: labels · RightLabel/time · error-label ──┘
```

- **Title** (`data-testid="task-row-title"`): replace `truncate` with
  `line-clamp-2 break-words`; full width of the flex-1 column; keep
  `line-through text-life-ink-3` when done. Fixes #5.
- **Meta line** (`data-testid="task-row-meta"`): move the existing
  `TaskRowLabels` and `RightLabel` (incl. their testids
  `task-row-labels` / `task-row-label-chip` / `task-row-label-overflow`
  / `task-row-completed-at` / `task-row-routine`) and the error pill
  here, beneath the title, smaller. Behaviour of each sub-piece
  unchanged — only the container moves. Fixes #1.
- **Checkbox + avatar**: unchanged markup (keep `role=button`,
  `aria-label` "Mark as done/not done", `data-variant` live/stalled/
  errored rings). Align to line 1 via `mt-0.5`/items-start. #3 = no
  change.
- **Action affordance** (#4): drop the always-rendered opacity-0 caret
  span (the phantom gap). Make `RowQuickActions` **persistently
  visible** but low-contrast (`text-life-ink-3`, no `opacity-0`;
  hover/focus darkens) — keep testids `task-row-assign-to-agent` /
  `task-row-run-now` and the show-rules (assign on user tasks, run-now
  on assistant+do_at). When there's no action, render nothing (no
  reserved width). Touch users now see it; desktop no longer has an
  empty hover-only slot.
- Row stays one clickable element (`onOpen`, selection-safe handler
  unchanged).

## B. Collapsible hierarchy — `frontend/src/screens/Tasks/TwoAxisList.tsx`

Make the two tiers obviously different (#2):

- **Outer** (owner / label group header): primary. `text-[15px]
  font-semibold text-life-ink`, full-width with a `border-b
  border-life-line` rule and a bit more vertical space; caret on the
  left, count as a muted pill. `data-testid="outer-group-header"`.
- **Outer content indented**: wrap the inner block in `pl-3` (small,
  mobile-safe) so nested sections visibly sit *under* the group.
- **Inner** `SectionHeader` (Waiting/Scheduled/Done): secondary —
  keep small uppercase `text-[11px] tracking-[0.6px] text-life-ink-3`,
  **no rule**, a smaller caret, sitting in the indented column.
  `data-testid="section-header"`.
- Net: outer = bold + rule + flush-left; inner = quiet uppercase +
  indented + lighter. Clear parent/child read.
- `groupBy="none"`: no outer header (single implicit group) → inner
  sections are the only tier, rendered without the extra indent so a
  flat view doesn't look needlessly nested.
- `TaskGroupsView` (status path) keeps its current headers — out of
  scope for this round (its Done-only collapse already reads fine);
  note for a later consistency pass.

## C. Tests

- `frontend/src/screens/Tasks/TaskRow.test.tsx` — keep all 19 existing
  assertions green (testids/roles/variants preserved by design). Add:
  - title node has `task-row-title`, class includes `line-clamp-2`,
    **not** `truncate`; a long title renders without being clipped to
    one line (assert class, not pixels).
  - meta node `task-row-meta` contains the label chips + completed-at.
  - quick-action button is in the DOM **without** hovering and is not
    `opacity-0` (assert className lacks `opacity-0`).
  - no phantom caret: the old hover caret span is gone.
- `frontend/src/screens/Tasks/TwoAxisList.test.tsx` — add: in
  `assignee` grouping, `outer-group-header` present and distinct from
  `section-header`; inner sections nested under it; `none` grouping has
  no `outer-group-header`. Keep existing `/^Done/` etc. queries green.
- Storybook (`TwoAxisTaskList.stories.tsx`) auto-reflects; eyeball
  ByOwner/Flat/ByLabel.
- Gates: `pnpm typecheck`, `pnpm vitest run src/screens/Tasks`,
  `pnpm build`.

## D. Out of scope / deferred

- `TaskGroupsView` header restyle (status path) — later consistency
  pass.
- Row density/virtualization unchanged (cursor pager still bounds the
  done DOM).
- No backend changes.
