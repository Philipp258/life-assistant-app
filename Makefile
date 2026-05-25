.PHONY: dev backend frontend set-password gen-vapid

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

gen-vapid:
	cd backend && uv run python scripts/gen_vapid_keys.py $(ARGS)
