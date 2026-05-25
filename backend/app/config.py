import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


def _shared_env_path() -> Path:
    """One machine-level secrets file shared by every git worktree.

    Secrets (provider keys, LANGFUSE_*, …) live here so they propagate to
    all worktrees instantly — add/rotate once, every checkout sees it on
    next boot. The per-worktree .env only carries overrides (ports,
    branch SESSION_SECRET). Override the location with LIFE_ASSISTANT_SHARED_ENV.
    """
    return Path(
        os.environ.get("LIFE_ASSISTANT_SHARED_ENV")
        or Path.home() / ".config" / "life-assistant" / ".env"
    )


SHARED_ENV = _shared_env_path()
DATA_DIR = Path(os.environ.get("LIFE_ASSISTANT_DATA_DIR") or REPO_ROOT / "data").resolve()
DEFAULT_DB_PATH = DATA_DIR / "life_assistant.db"
CORE_DIR = DATA_DIR / "core"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
SKILLS_DIR = DATA_DIR / "skills"
DEFAULTS_SKILLS_DIR = REPO_ROOT / "backend" / "defaults" / "skills"
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Loaded in order; later wins. Shared secrets first, then the
        # worktree .env so its ports/SESSION_SECRET override. Missing
        # files are silently skipped (fresh clone with no shared file).
        env_file=(SHARED_ENV, REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "dev"
    database_url: str = f"sqlite:///{DEFAULT_DB_PATH}"
    serve_frontend: bool = False

    # Langfuse tracing (OpenTelemetry). All three required to enable; any
    # left unset → fully no-op. Names mirror the Langfuse SDK's own env
    # vars so a stock Langfuse .env block works as-is.
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_base_url: str | None = None

    sentry_dsn: str | None = None
    sentry_release: str | None = None
    sentry_traces_sample_rate: float = 0.0
    sentry_profiles_sample_rate: float = 0.0

    # Signs the session cookie. Generate with `python -c 'import secrets;
    # print(secrets.token_hex(32))'`. Required at runtime; left optional
    # here so import-time tooling (alembic, ruff) doesn't blow up before
    # .env is populated.
    session_secret: str | None = None
    session_max_age_seconds: int = 60 * 60 * 24 * 30

    # pydantic-ai per-run model request cap. The library default is 50, which
    # is too low for long autonomous task turns because every tool-call round
    # trip can consume another model request. Life Assistant disables this request-count
    # cap explicitly; token/provider limits still apply.
    agent_request_limit: int | None = None

    # Main-chat compaction. When the persisted history (excluding rows
    # already marked `compacted_at`) exceeds `compaction_trigger_tokens`,
    # everything older than the last `compaction_keep_groups` message
    # groups is rolled into a single LLM-generated summary. Triggers are
    # token-based (not turn-based) so the cache prefix stays stable
    # between compaction events.
    compaction_trigger_tokens: int = 80_000
    compaction_keep_groups: int = 8

    # Web Push (VAPID). Generate with `uv run python backend/scripts/gen_vapid_keys.py`.
    # `vapid_private_key_path` may be either an absolute path or relative to
    # the repo root. `vapid_public_key` is the urlsafe-base64 raw P-256
    # uncompressed point string browsers expect for `applicationServerKey`.
    # If any are unset, push fanout no-ops with a single startup warning so
    # the rest of the app keeps booting.
    vapid_private_key_path: str | None = None
    vapid_public_key: str | None = None
    vapid_contact_email: str | None = None


settings = Settings()
