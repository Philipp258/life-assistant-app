from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth.middleware import SessionAuthMiddleware
from app.auth.router import router as auth_router
from app.chat.router import router as chat_router
from app.config import FRONTEND_DIST, settings
from app.health.router import router as health_router
from app.knowledge.router import router as knowledge_router
from app.labels.router import router as labels_router
from app.notifications.router import router as notifications_router
from app.observability import flush_observability, setup_observability, setup_sentry
from app.provider_settings.router import (
    legacy_router as provider_settings_legacy_router,
    router as provider_settings_router,
)
from app.saved_task_views.router import router as saved_task_views_router
from app.settings.router import router as runtime_settings_router
from app.skills.router import router as skills_router
from app.tasks.router import router as tasks_router
from app.users.router import router as users_router
from app.voice.router import router as voice_router


def seed_repo_defaults(db) -> None:
    """Materialize repo-shipped defaults that should exist on every install."""
    from app.saved_task_views.defaults import ensure_default_saved_views
    from app.tasks.default_routines import ensure_default_routines

    ensure_default_routines(db)
    ensure_default_saved_views(db)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Touch the engine so WAL pragmas run on first connect.
    from app.db import engine

    with engine.connect():
        pass

    # Make sure data/core/{about_user,behavior}.md and data/knowledge/
    # exist; agents read them on every turn. Default skills now live
    # under backend/defaults/skills/ (tracked in git, immutable) so
    # there is nothing to seed under data/skills/ — only user-installed
    # skills live there.
    from app.config import KNOWLEDGE_DIR, SKILLS_DIR
    from app.knowledge import core as core_memory

    core_memory.seed_if_missing()
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

    # One-time migration: earlier versions seeded the three default
    # skills into data/skills/. Now defaults are read from the repo, so
    # any on-disk copy under data/skills/ would shadow the live default
    # and silently freeze it at the version that shipped on first boot.
    # Delete unconditionally; users who want a custom variant can
    # install it under a different name.
    import logging

    log = logging.getLogger("app.main")
    for slug in ("add-skills", "github", "self-update"):
        legacy = SKILLS_DIR / slug / "SKILL.md"
        if legacy.is_file():
            try:
                legacy.unlink()
                # Best-effort: drop the slug folder if now empty.
                with suppress(OSError):
                    legacy.parent.rmdir()
                log.info("startup: removed legacy default skill %s", legacy)
            except OSError as exc:
                log.warning(
                    "startup: failed to remove legacy default skill %s: %s",
                    legacy,
                    exc,
                )

    # Ensure the singleton main chat exists at boot, plus the
    # singleton user row so onboarding can flip its flag. Repo defaults
    # (assistant routines and saved task views) are also seeded
    # idempotently at every boot; there is intentionally no runtime
    # env/config switch because missing defaults are user-visible.
    from app.chat.service import get_or_create_main_session
    from app.db import SessionLocal
    from app.users.service import ensure_user

    with SessionLocal() as db:
        ensure_user(db)
        get_or_create_main_session(db)
        seed_repo_defaults(db)

    # Capture the main event loop so `schedule_wake` can dispatch wakes
    # from sync FastAPI routes (which run in a threadpool) and sync
    # pydantic-ai tools (which run via `run_in_executor`).
    import asyncio

    from app.chat import runner

    runner.set_main_loop(asyncio.get_running_loop())
    log.info("startup: main loop captured for runner")

    # Recover any task chats that were in flight before the restart.
    in_flight = runner.list_in_flight_tasks()
    log.info("startup: recovering %d in-flight task session(s)", len(in_flight))
    for task in in_flight:
        runner.schedule_wake(task.chat_session_id)

    # Belt-and-suspenders: a watchdog periodically re-pokes any in-flight
    # task whose runner isn't currently active. Catches missed wakes from
    # any code path so the user never sees a "stuck" autonomous task.
    runner.start_watchdog()

    # Periodic Web Push fan-out for tasks whose due_at has passed.
    from app.notifications import due_scheduler

    due_scheduler.start()

    try:
        yield
    finally:
        runner.stop_watchdog()
        due_scheduler.stop()
        flush_observability()


setup_sentry()
app = FastAPI(title="Life Assistant", lifespan=lifespan)

if not settings.session_secret:
    raise RuntimeError(
        "SESSION_SECRET is not set. Generate one with "
        "`python -c 'import secrets; print(secrets.token_hex(32))'` "
        "and add it to .env."
    )

# Order matters: middleware added later runs first on the way in. We want
# SessionMiddleware to populate request.session before SessionAuthMiddleware
# checks it, so SessionMiddleware is added last.
app.add_middleware(SessionAuthMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="life_assistant_session",
    max_age=settings.session_max_age_seconds,
    same_site="lax",
    https_only=settings.env == "prod",
)

setup_observability(app)

app.include_router(health_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(labels_router, prefix="/api")
app.include_router(saved_task_views_router, prefix="/api")
app.include_router(knowledge_router, prefix="/api")
app.include_router(skills_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(notifications_router, prefix="/api")
app.include_router(provider_settings_router, prefix="/api")
app.include_router(provider_settings_legacy_router, prefix="/api")
app.include_router(runtime_settings_router, prefix="/api")
app.include_router(voice_router, prefix="/api")


# API callers expect JSON. Without this, the SPA catch-all below would
# answer unknown `/api/...` paths with the index.html document and a 200,
# which makes stale clients crash with "Unexpected token '<'" when they
# call `response.json()`. Registered after every router so real API
# routes still win on match.
@app.api_route(
    "/api",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
def api_root_not_found() -> JSONResponse:
    return JSONResponse({"detail": "Not Found"}, status_code=404)


@app.api_route(
    "/api/{full_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
def api_not_found(full_path: str) -> JSONResponse:
    return JSONResponse({"detail": "Not Found"}, status_code=404)


# Vite emits content-hashed filenames under /assets/, so the bytes
# behind any given URL never change. Tell browsers and installed PWAs
# they can cache them forever and skip revalidation.
_IMMUTABLE_CACHE = "public, max-age=31536000, immutable"

# Entry points that must always be revalidated. Without no-cache the
# installed PWA WebView can pin a stale app shell (or service worker)
# indefinitely via heuristic freshness, and the UI lags the deployed
# build until the user manually clears storage. See #173.
_NO_CACHE_PATHS = frozenset({"sw.js", "index.html", "manifest.webmanifest"})
_NO_CACHE_HEADERS = {"Cache-Control": "no-cache, no-store, must-revalidate"}

_MEDIA_TYPE_OVERRIDES = {
    ".webmanifest": "application/manifest+json",
}


class _ImmutableStaticFiles(StaticFiles):
    async def get_response(self, path, scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = _IMMUTABLE_CACHE
        return response


def mount_frontend(app: FastAPI, dist: Path) -> None:
    """Wire up the SPA + PWA static asset routes.

    Split out so tests can exercise the cache-header policy without
    flipping `settings.serve_frontend` at import time.
    """
    assets_dir = dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", _ImmutableStaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str) -> FileResponse:
        target = dist / full_path
        if full_path and target.is_file():
            media_type = _MEDIA_TYPE_OVERRIDES.get(target.suffix)
            headers = _NO_CACHE_HEADERS if full_path in _NO_CACHE_PATHS else None
            if media_type is not None:
                return FileResponse(target, media_type=media_type, headers=headers)
            return FileResponse(target, headers=headers)
        return FileResponse(dist / "index.html", headers=_NO_CACHE_HEADERS)


if settings.serve_frontend and FRONTEND_DIST.is_dir():
    mount_frontend(app, FRONTEND_DIST)
