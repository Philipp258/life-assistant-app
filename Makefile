.PHONY: dev backend frontend set-password set-assistant-name set-user-name gen-vapid

# Per-worktree overrides come from .env (set by scripts/wtree.sh).
BACKEND_PORT ?= 8000
FRONTEND_PORT ?= 5173

dev:
	@trap 'kill 0' INT TERM; \
	$(MAKE) -j2 backend frontend

backend:
	cd backend && uv run uvicorn app.main:app --reload --port $(BACKEND_PORT)

frontend:
	cd frontend && pnpm dev --port $(FRONTEND_PORT)

set-password:
	@if [ -z "$(PASSWORD)" ]; then echo "usage: make set-password PASSWORD=<pw>" >&2; exit 2; fi
	cd backend && uv run python -m app.users.set_password "$(PASSWORD)"

set-assistant-name:
	@if [ -z "$(NAME)" ]; then echo "usage: make set-assistant-name NAME=<name>" >&2; exit 2; fi
	cd backend && uv run python -m app.knowledge.set_name --assistant "$(NAME)"

set-user-name:
	@if [ -z "$(NAME)" ]; then echo "usage: make set-user-name NAME=<name>" >&2; exit 2; fi
	cd backend && uv run python -m app.knowledge.set_name --user "$(NAME)"

gen-vapid:
	cd backend && uv run python scripts/gen_vapid_keys.py $(ARGS)
