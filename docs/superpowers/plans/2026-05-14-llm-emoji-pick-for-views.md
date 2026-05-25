# LLM Emoji Pick for Saved Task Views — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the user creates a saved task view through the `+` tab button, the backend uses the configured LLM to pick a single fitting emoji from the Unicode emoji set, then stores it on the new view. Picking is synchronous and blocking — view creation waits up to ~3 seconds for the LLM response. If the LLM fails or times out, the view is created with `icon = null` and the UI falls back to a letter avatar derived from the name.

**Architecture:** A small helper `pick_emoji_for_view(name, filters, labels)` in `backend/app/saved_task_views/emoji.py` constructs a one-shot pydantic-ai run against the existing agent's configured model (z.ai or OpenRouter, per `app/agent/__init__.py`). The helper enforces a short token budget and a one-character output. The view router calls the helper inline during `POST /api/saved-task-views`; the frontend's `NewViewNamePrompt` already blocks on the request, so no extra UI work is needed beyond rendering the returned emoji on the new tab.

**Tech Stack:** Python 3.11, pydantic-ai, the existing provider plumbing under `backend/app/agent/providers/`. Frontend: React 18, TS.

**Prerequisite:** Plan `2026-05-14-saved-task-views.md` must be merged first.

**Non-goals:**
- Re-running emoji selection when a view is renamed. The user can override via the kebab → `Change icon` flow (not in this plan).
- Background async updates if the sync call times out — failure → null icon, that's the contract.
- Curated monochrome Unicode subset — the LLM picks from the full emoji set.

**File map**

Created:
- `backend/app/saved_task_views/emoji.py`
- `backend/tests/test_saved_task_views_emoji.py`

Modified:
- `backend/app/saved_task_views/router.py` — call `pick_emoji_for_view` on create.
- `backend/app/saved_task_views/schemas.py` — `SavedTaskViewCreate.icon` becomes optional input; server can override.

---

### Task 1: emoji helper module

**Files:**
- Create: `backend/app/saved_task_views/emoji.py`
- Create: `backend/tests/test_saved_task_views_emoji.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/test_saved_task_views_emoji.py
from unittest.mock import MagicMock

import pytest

from app.saved_task_views import emoji


def test_extract_one_emoji_picks_first_emoji_character():
    assert emoji.extract_one_emoji("Sure, I'd pick 🏠 for a home view.") == "🏠"


def test_extract_one_emoji_returns_none_when_absent():
    assert emoji.extract_one_emoji("no glyph here") is None


def test_pick_emoji_for_view_returns_extracted(monkeypatch):
    fake = MagicMock(return_value="✨")
    monkeypatch.setattr(emoji, "_run_llm", fake)
    out = emoji.pick_emoji_for_view(name="Home", filters={"labels": ["home"]})
    assert out == "✨"
    fake.assert_called_once()


def test_pick_emoji_for_view_returns_none_on_timeout(monkeypatch):
    def boom(_prompt: str, *, timeout_s: float) -> str:
        raise TimeoutError("nope")

    monkeypatch.setattr(emoji, "_run_llm", boom)
    assert emoji.pick_emoji_for_view(name="Home", filters={}) is None


def test_pick_emoji_for_view_returns_none_when_llm_returns_nothing_useful(monkeypatch):
    monkeypatch.setattr(emoji, "_run_llm", lambda *_a, **_k: "I'm not sure.")
    assert emoji.pick_emoji_for_view(name="x", filters={}) is None
```

- [ ] **Step 2: Run, fail**

```bash
cd backend && uv run pytest tests/test_saved_task_views_emoji.py -v
```

- [ ] **Step 3: Implement**

```python
# backend/app/saved_task_views/emoji.py
from __future__ import annotations

import re
from typing import Any

from app.agent import get_agent  # uses existing pydantic-ai agent + model selection

# Emoji codepoint ranges that count as a "real" pick. Skips digits, regional
# indicators alone, etc. Tightened to common pictographic blocks.
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001F6FF\U0001F900-\U0001F9FF\U00002600-\U000026FF\U00002700-\U000027BF]"
)

_PROMPT = (
    "Pick exactly one emoji that fits a saved task-view with these properties.\n"
    "Reply with the single emoji character only — no words, no punctuation.\n"
    "View name: {name}\n"
    "Filters: {filters}\n"
    "Labels: {labels}\n"
)


def extract_one_emoji(text: str) -> str | None:
    match = _EMOJI_RE.search(text or "")
    return match.group(0) if match else None


def _run_llm(prompt: str, *, timeout_s: float) -> str:
    """Real-LLM round-trip. Patched in tests."""
    agent = get_agent()
    # pydantic-ai sync wrapper around the configured model. Constrain output
    # by asking for a tiny reply; we'll truncate downstream anyway.
    result = agent.run_sync(prompt, model_settings={"max_tokens": 8})  # type: ignore[arg-type]
    return result.output or ""


def pick_emoji_for_view(
    *,
    name: str,
    filters: dict[str, Any],
    labels: list[str] | None = None,
    timeout_s: float = 3.0,
) -> str | None:
    prompt = _PROMPT.format(
        name=name,
        filters=filters,
        labels=labels or [],
    )
    try:
        raw = _run_llm(prompt, timeout_s=timeout_s)
    except Exception:
        return None
    return extract_one_emoji(raw)
```

Verify `get_agent` actually exists in `app.agent.__init__`. From the earlier exploration the module exposes `_build_agent` and caches an agent (line 436). Add a public accessor if not already present:

```python
# backend/app/agent/__init__.py — append
def get_agent() -> Agent[AgentDeps, str]:
    """Return the cached pydantic-ai agent, building it on first call."""
    global _agent
    if _agent is None:
        _agent = _build_agent()
    return _agent
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/test_saved_task_views_emoji.py -v
git add backend/app/saved_task_views/emoji.py backend/app/agent/__init__.py backend/tests/test_saved_task_views_emoji.py
git commit -m "feat(views): emoji-picker helper using existing agent"
```

---

### Task 2: Wire helper into view creation

**Files:**
- Modify: `backend/app/saved_task_views/router.py`
- Modify: `backend/app/saved_task_views/schemas.py` (no shape change but a comment update)
- Modify: `backend/tests/test_saved_task_views_router.py` (extend)

- [ ] **Step 1: Failing tests**

Append to `backend/tests/test_saved_task_views_router.py`:

```python
from unittest.mock import patch


@patch("app.saved_task_views.router.pick_emoji_for_view", return_value="🏠")
def test_create_uses_llm_for_icon_when_omitted(mock_pick):
    body = {"name": "Home", "filters": {"labels": ["home"]}, "group_by": "none"}
    resp = client.post("/api/saved-task-views", json=body)
    assert resp.status_code == 201
    assert resp.json()["icon"] == "🏠"
    mock_pick.assert_called_once()


@patch("app.saved_task_views.router.pick_emoji_for_view", return_value="🏠")
def test_create_keeps_explicit_icon(mock_pick):
    body = {"name": "Home", "icon": "🛖", "filters": {}, "group_by": "none"}
    resp = client.post("/api/saved-task-views", json=body)
    assert resp.json()["icon"] == "🛖"
    mock_pick.assert_not_called()


@patch("app.saved_task_views.router.pick_emoji_for_view", return_value=None)
def test_create_falls_back_to_null_icon_when_llm_fails(_mock):
    body = {"name": "Home", "filters": {}, "group_by": "none"}
    resp = client.post("/api/saved-task-views", json=body)
    assert resp.json()["icon"] is None
```

- [ ] **Step 2: Run, fail**

```bash
cd backend && uv run pytest tests/test_saved_task_views_router.py -v
```

- [ ] **Step 3: Update router**

In `backend/app/saved_task_views/router.py`:

```python
from app.saved_task_views.emoji import pick_emoji_for_view


@router.post("/saved-task-views", status_code=status.HTTP_201_CREATED)
def create_view(body: SavedTaskViewCreate) -> SavedTaskViewRead:
    icon = body.icon
    if icon is None:
        icon = pick_emoji_for_view(
            name=body.name,
            filters=body.filters,
            labels=body.filters.get("labels", []),
        )
    body_with_icon = body.model_copy(update={"icon": icon})
    with SessionLocal() as session:
        view = service.create_view(session, body_with_icon)
        return SavedTaskViewRead.from_orm_row(view)
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/test_saved_task_views_router.py -v
git add backend/app/saved_task_views/router.py backend/tests/test_saved_task_views_router.py
git commit -m "feat(views): call LLM emoji picker on create when no icon given"
```

---

### Task 3: Frontend — letter-avatar fallback when icon is null

**Files:**
- Modify: `frontend/src/screens/Tasks/SavedTaskViews/SavedTaskViewTabs.tsx`
- Modify: `frontend/src/screens/Tasks/SavedTaskViews/SavedTaskViewTabs.test.tsx`

- [ ] **Step 1: Failing test**

```tsx
it("renders the first letter when icon is null", () => {
  const noIcon = { id: 3, name: "Errands", icon: null, filters: {}, group_by: "none" as const, sort_index: 2, is_default: false };
  render(
    <SavedTaskViewTabs
      views={[noIcon]}
      activeId={3}
      dirty={false}
      onSelect={() => {}}
      onRename={() => {}}
      onMakeDefault={() => {}}
      onDelete={() => {}}
      onAdd={() => {}}
    />,
  );
  expect(screen.getByText("E")).toBeInTheDocument();
});
```

- [ ] **Step 2: Implement letter avatar**

In `SavedTaskViewTabs.tsx`, replace `<span>{view.icon}</span>` with:

```tsx
{view.icon
  ? <span>{view.icon}</span>
  : <span className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-life-bg text-[10px] font-semibold text-life-ink-2">
      {view.name.slice(0, 1).toUpperCase() || "?"}
    </span>
}
```

- [ ] **Step 3: Tests pass + commit**

```bash
cd frontend && pnpm vitest run src/screens/Tasks/SavedTaskViews/SavedTaskViewTabs.test.tsx
git add frontend/src/screens/Tasks/SavedTaskViews
git commit -m "feat(views): letter-avatar fallback when icon is null"
```

---

### Task 4: Frontend — show "Picking emoji…" while POST in flight

**Files:**
- Modify: `frontend/src/screens/Tasks/SavedTaskViews/useSavedTaskViews.ts`
- Modify: the name-prompt component within TasksScreen wiring.

- [ ] **Step 1: Add `pending` state in the hook**

```ts
const [creating, setCreating] = useState(false);

const createFromWorking = useCallback(async (name: string, icon: string | null) => {
  setCreating(true);
  try {
    const created = await createView({ name, icon, filters: workingFilters, group_by: workingGroupBy });
    setViews((curr) => [...curr, created]);
    setActiveId(created.id);
    return created;
  } finally {
    setCreating(false);
  }
}, [workingFilters, workingGroupBy]);
```

Return `creating` from the hook.

- [ ] **Step 2: Surface in name prompt**

Disable the `Create` button while `creating` is true and show a small `Picking emoji…` line below the input. Keep the input focused. No spinner — copy is enough.

- [ ] **Step 3: Test that the button disables**

In `TasksScreen.test.tsx`, mock `createView` to return a never-resolving promise, click Create, assert the button is disabled and the helper text appears.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/screens/Tasks
git commit -m "feat(views): name prompt shows pending state while LLM picks emoji"
```

---

### Task 5: CI parity

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest
cd frontend && pnpm typecheck && pnpm test && pnpm build
```

Commit any formatter fixes; push.

---

## Test coverage map

| Behavior | Test file |
|---|---|
| Emoji regex extracts and rejects | `backend/tests/test_saved_task_views_emoji.py` |
| Helper short-circuits on timeout / non-emoji LLM output | same |
| Router uses helper when icon omitted | `backend/tests/test_saved_task_views_router.py` (added cases) |
| Router preserves explicit icon | same |
| Router writes null icon when helper returns None | same |
| Tab letter-avatar fallback | `SavedTaskViewTabs.test.tsx` (added case) |
| Name prompt disables Create while pending | `TasksScreen.test.tsx` (added case) |

## Risk notes

- **Latency.** A 3s blocking call is acceptable here because view creation is rare, but a slow provider on a bad network could feel sluggish. Watch the p50 in `app/observability.py` after rollout; if it's painful, swap to a smaller model just for this call (override `model_settings` in `_run_llm`).
- **Cost.** One small request per view-create — single-user app, negligible.
- **Token splitting.** Less-common emoji are split across multiple tokens and degrade picks. The prompt is short and we accept whatever the model emits, so the worst case is a null icon → letter fallback; user can override later.
- **Prompt-injection from labels.** Names and label slugs are user-controlled. The LLM is asked only to emit one character; any attempt to coerce more text will be discarded by `extract_one_emoji`. Don't extend the prompt to ask the model to act on label content.
