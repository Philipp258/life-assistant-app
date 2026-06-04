# AGENTS.md

Coding-agent guide for the assistant-app repo. Light on rules, heavier on
"how things actually work" — once the shape of the project is in your
head, the rules write themselves.

## What this is

Life Assistant is a personal-assistant app: one VPS, one user, one process.
FastAPI + SQLite serving `/api/*` plus a React/TypeScript SPA.
The "agent" *inside* the running app (pydantic-ai, talks to z.ai /
OpenRouter / Codex) is a different thing from the coding agent reading
this file. Don't confuse them — when this file says "the agent" it
means the assistant's runtime agent.

## Layout

- `backend/` — Python 3.11, FastAPI, SQLAlchemy + Alembic, pydantic-ai,
  managed with `uv`. Runtime agent in `backend/app/agent/`. Default
  runtime skills the agent loads at boot live under
  `backend/defaults/skills/<name>/SKILL.md` and are read-only by design
  (the runtime FS tools refuse writes); user-installed skills land in
  `data/skills/`.
- `frontend/` — React 18 + Vite + TS + Tailwind, managed with `pnpm`.
  Tests via Vitest; some screens have Storybook stories.
- `deploy/` — systemd units and install/update/backup scripts for the VPS.
- `scripts/cmux_slots.py` — opens/reuses cmux workspaces for the six fixed
  local slots under `/Users/philipp/Projects/life-assistant-app-slot-N`.

## Running things

`make dev` boots backend (uvicorn :8000) and frontend (vite :5173)
together — that's the normal local loop.

Backend, from `backend/`:

- `uv sync`
- `uv run ruff check .` and `uv run ruff format --check .`
- `uv run pytest`
- `uv run alembic upgrade head` to apply migrations

Frontend, from `frontend/`:

- `pnpm install --frozen-lockfile`
- `pnpm typecheck`
- `pnpm build`
- `pnpm test`

Choose local checks that match the files you changed. 

## Style

- Conventional Commits for commit and PR titles (`feat:`, `fix:`, `ci:`, …).
- Python: ruff with line length 100, target py311. 
- TypeScript: `pnpm typecheck` is the source of truth.
- The app is mobile-only. Design and build for the phone viewport first;
  avoid desktop-only navigation patterns such as split panes or persistent
  sidebars in production flows. 

## Gotchas

- `data/` is the live persistent store: `data/life_assistant.db` (SQLite + WAL
  sidecars), `data/core/`, `data/knowledge/`, user-installed
  `data/skills/`. Don't read or write `data/*.db*` directly — go through
  SQLAlchemy. Nothing under `data/` should be committed.
- Migrations live in `backend/alembic/versions/`. Keep them single-head.
- `SESSION_SECRET` is required to boot — see `.env.example`.

## Working on PRs

Include `Closes #<n>` in the PR body when the work resolves an issue.
Push fixes to the existing branch instead of opening a replacement PR.
Don't merge — a human does that.

## Writing for agents (any agent)

This file is the coding-agent guide, but the same pattern applies to
every prompt in the repo: the assistant's runtime prompts in
`backend/app/agent/__init__.py` and default skills under
`backend/defaults/skills/<name>/SKILL.md`.

Write prompts like you are briefing a capable teammate:

- Start minimal. Add nothing unless you know it is needed.
- Lead with intent and context: what the agent is trying to accomplish,
  where it is operating, what information it can trust, and what outcome
  matters.
- Assume the agent can make smart local decisions. Don't spell out obvious
  steps, available commands, or tool mechanics that are already visible
  from the environment.
- Use rigid rules only when you are sure they are needed
- Prefer a small example over a broad rule when the example communicates
  the pattern more clearly.

Be precise about whose perspective the prompt is written from. A coding
agent editing a prompt is outside the app; the runtime agent reading that
prompt is inside the app with its own tools, memory, filesystem view, and
user conversation. Write instructions for the agent that will actually read
them. 
