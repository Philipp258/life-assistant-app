"""Shared pytest fixtures.

Each test gets an isolated sqlite file. Routers and tool modules import
`SessionLocal` at module load time, so we re-bind it on each import site
instead of only on `app.db`.
"""

from __future__ import annotations

import os
import logging
from pathlib import Path

import pytest


_PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "FTP_PROXY",
    "GRPC_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "ftp_proxy",
    "grpc_proxy",
)


@pytest.fixture(autouse=True)
def _restore_logging_disable_threshold():
    """Keep tests that assert warning logs isolated from global logging state."""
    previous = logging.root.manager.disable
    app_logger_state = {
        name: (logger.disabled, logger.propagate)
        for name, logger in logging.root.manager.loggerDict.items()
        if name == "app" or name.startswith("app.")
        if isinstance(logger, logging.Logger)
    }
    logging.disable(logging.NOTSET)
    for logger_name in app_logger_state:
        logger = logging.getLogger(logger_name)
        logger.disabled = False
        logger.propagate = True
    yield
    logging.disable(previous)
    for logger_name, (disabled, propagate) in app_logger_state.items():
        logger = logging.getLogger(logger_name)
        logger.disabled = disabled
        logger.propagate = propagate


@pytest.fixture(autouse=True)
def _reset_runner_state():
    """Clear process-global runner state between tests.

    `runner._session_locks` is a module-global `defaultdict(asyncio.Lock)`.
    A Lock first awaited under one test's event loop (e.g. a TestClient
    WebSocket turn) is bound to that loop; the next test that drives the
    same session id under a fresh `asyncio.run` loop would reuse the same
    Lock object and trip asyncio's loop-binding guard. Resetting per test
    keeps each test's locks bound to its own loop. The transient voice /
    activity / wake-timestamp maps are cleared for the same isolation
    reason.
    """
    from app.chat import runner as _runner

    for attr in (
        "_session_locks",
        "_pending_voice",
        "_last_wake_at",
        "_active_sessions",
    ):
        getattr(_runner, attr).clear()
    yield
    for attr in (
        "_session_locks",
        "_pending_voice",
        "_last_wake_at",
        "_active_sessions",
    ):
        getattr(_runner, attr).clear()


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    """Login rate limit holds process-global per-IP counters."""
    from app.auth import rate_limit

    rate_limit._reset_for_tests()
    yield
    rate_limit._reset_for_tests()


@pytest.fixture(autouse=True)
def _allow_model_requests():
    """Reset pydantic-ai's ALLOW_MODEL_REQUESTS before each test.

    test_runner and test_events set this to False at module level
    as a safety net, but that leaks into other test modules. This fixture
    ensures each test starts with the flag True; tests that need it False
    use agent.override(model=FunctionModel(...)) which is the real guard.
    """
    from pydantic_ai import models

    original = models.ALLOW_MODEL_REQUESTS
    models.ALLOW_MODEL_REQUESTS = True
    yield
    models.ALLOW_MODEL_REQUESTS = original


@pytest.fixture(autouse=True)
def _strip_proxy_env(monkeypatch: pytest.MonkeyPatch):
    """Tests must not inherit shell SOCKS/HTTP proxies.

    httpx picks them up via `trust_env=True`, which makes `OpenAIProvider`
    fail to build (and would try real network if it didn't).
    """
    for var in _PROXY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _no_network_credential_probe(monkeypatch: pytest.MonkeyPatch):
    """Credential verification must never hit the real network in tests.

    The OpenAI-compatible probe in `provider_settings.verify` is the
    only networked path. Default it to a connection failure, which the
    verifier treats as "could not disprove the key" → allow through —
    so round-trip tests using placeholder keys still pass. Tests that
    assert probe behaviour (401/200) re-patch `httpx.get` themselves.
    """
    from app.provider_settings import verify as credential_verify

    def _offline(*_a: object, **_k: object):
        raise credential_verify.httpx.ConnectError("network disabled in tests")

    monkeypatch.setattr(credential_verify.httpx, "get", _offline)


@pytest.fixture(autouse=True)
def _isolate_data_dirs(tmp_path_factory, monkeypatch: pytest.MonkeyPatch):
    """Point CORE/KNOWLEDGE/SKILLS dirs at a per-test tmp tree.

    The app lifespan and many modules touch the real `data/` tree on
    import or boot (seed core memory, walk skills/knowledge, the
    legacy-default-skill cleanup migration). Without this, running the
    test suite would mutate the developer's local `data/`.

    Tests that need to control these dirs themselves can re-monkeypatch
    them — `monkeypatch` is LIFO so the local fixture wins.

    DEFAULTS_SKILLS_DIR is left pointing at the real
    `backend/defaults/skills/` so prompt-assembly + API tests see the
    real shipped defaults; tests that want an empty defaults set
    monkeypatch it themselves.
    """
    root = tmp_path_factory.mktemp("data")
    core = root / "core"
    knowledge = root / "knowledge"
    skills = root / "skills"
    for d in (core, knowledge, skills):
        d.mkdir(parents=True, exist_ok=True)

    import app.config as config_mod
    import app.knowledge.core as core_mod
    import app.knowledge.store as knowledge_store_mod
    import app.skills.store as skills_store_mod

    monkeypatch.setattr(config_mod, "DATA_DIR", root, raising=True)
    monkeypatch.setattr(config_mod, "CORE_DIR", core, raising=True)
    monkeypatch.setattr(config_mod, "KNOWLEDGE_DIR", knowledge, raising=True)
    monkeypatch.setattr(config_mod, "SKILLS_DIR", skills, raising=True)
    monkeypatch.setattr(core_mod, "CORE_DIR", core, raising=True)
    monkeypatch.setattr(knowledge_store_mod, "KNOWLEDGE_DIR", knowledge, raising=True)
    monkeypatch.setattr(skills_store_mod, "SKILLS_DIR", skills, raising=True)


@pytest.fixture
def _test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import app.db as db_module
    from app.db import Base

    test_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    TestSession = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)

    # Register every model so create_all covers them.
    from app.chat import models as _chat_models  # noqa: F401
    from app.defaults import models as _defaults_models  # noqa: F401
    from app.labels import models as _labels_models  # noqa: F401
    from app.notifications import models as _notif_models  # noqa: F401
    from app.provider_settings import models as _provider_settings_models  # noqa: F401
    from app.saved_task_views import models as _saved_task_views_models  # noqa: F401
    from app.settings import models as _settings_models  # noqa: F401
    from app.tasks import models as _tasks_models  # noqa: F401
    from app.users import models as _users_models  # noqa: F401

    Base.metadata.create_all(test_engine)

    # SessionMiddleware refuses to start without a secret. Use a fixed
    # value so signed cookies are stable across the test run.
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-not-for-prod")
    from app.config import settings as _settings

    monkeypatch.setattr(
        _settings,
        "session_secret",
        "test-session-secret-not-for-prod",
        raising=True,
    )
    # Force non-secure cookies in tests even when the outer process
    # happens to run with ENV=prod. TestClient uses http://testserver,
    # so Secure cookies would not be sent back to protected routes.
    monkeypatch.setattr(_settings, "env", "dev", raising=True)
    # Seed the singleton user as already-onboarded by default so tests
    # that hit /api/chat/main don't trip the onboarding greeting flow.
    # Onboarding-specific tests null this field explicitly.
    #
    # Also seed the singleton provider_settings row with a zai chat
    # credential so `get_agent()` can build a model in tests that
    # exercise the chat path (they `agent.override()` with a
    # FunctionModel before the real call). Tests that want to observe
    # the `needs_provider` onboarding state clear the credentials.
    from datetime import UTC, datetime
    import bcrypt

    with TestSession() as db:
        db.add(
            _users_models.User(
                password_hash=bcrypt.hashpw(b"test-pass", bcrypt.gensalt()).decode("utf-8"),
                onboarded_at=datetime.now(UTC),
            )
        )
        db.add(
            _provider_settings_models.ProviderSettings(
                id=1,
                zai_api_key="test-zai-key",
                zai_chat_model="glm-5.1",
                preferred_chat_provider="zai",
            )
        )
        # Mirror the post-onboarding invariant in production: both
        # identity names exist before any general-prompt rendering.
        # Onboarding-specific tests can clear these rows explicitly.
        db.add(_settings_models.AppSetting(key="assistant_name", value="Atlas"))
        db.add(_settings_models.AppSetting(key="user_name", value="Phil"))
        db.commit()

    monkeypatch.setattr(db_module, "engine", test_engine, raising=True)
    monkeypatch.setattr(db_module, "SessionLocal", TestSession, raising=True)

    # App-via-client tests assert exact task/view-list state; repo
    # default seeding would pollute it. Keep this as a test-only
    # monkeypatch instead of a runtime setting so production boots
    # always seed the shipped defaults.
    from app import main as main_mod

    monkeypatch.setattr(main_mod, "seed_repo_defaults", lambda db: None, raising=True)
    monkeypatch.setattr(main_mod, "SessionLocal", TestSession, raising=True)

    # Re-bind already-imported `SessionLocal` references.
    from app.tasks import router as tasks_router_mod

    monkeypatch.setattr(tasks_router_mod, "SessionLocal", TestSession, raising=True)

    from app.labels import router as labels_router_mod

    monkeypatch.setattr(labels_router_mod, "SessionLocal", TestSession, raising=True)

    from app.saved_task_views import router as saved_task_views_router_mod

    monkeypatch.setattr(saved_task_views_router_mod, "SessionLocal", TestSession, raising=True)

    from app.agent.tools import tasks as tasks_tools_mod

    monkeypatch.setattr(tasks_tools_mod, "SessionLocal", TestSession, raising=True)

    from app.chat import router as chat_router_mod

    monkeypatch.setattr(chat_router_mod, "SessionLocal", TestSession, raising=True)

    from app.chat import ws as chat_ws_mod

    monkeypatch.setattr(chat_ws_mod, "SessionLocal", TestSession, raising=True)

    from app.chat import runner as chat_runner_mod

    monkeypatch.setattr(chat_runner_mod, "SessionLocal", TestSession, raising=True)

    from app.agent.tools import sessions as session_tools_mod

    monkeypatch.setattr(session_tools_mod, "SessionLocal", TestSession, raising=True)

    from app.agent.tools import chats as chat_tools_mod

    monkeypatch.setattr(chat_tools_mod, "SessionLocal", TestSession, raising=True)

    from app.agent.tools import archived_messages as archived_messages_tools_mod

    monkeypatch.setattr(archived_messages_tools_mod, "SessionLocal", TestSession, raising=True)

    from app.agent.tools import web as web_tools_mod

    monkeypatch.setattr(web_tools_mod, "SessionLocal", TestSession, raising=True)

    from app.agent.tools import settings as settings_tools_mod

    monkeypatch.setattr(settings_tools_mod, "SessionLocal", TestSession, raising=True)

    from app.agent.tools import _task_scope as task_scope_mod

    monkeypatch.setattr(task_scope_mod, "SessionLocal", TestSession, raising=True)

    from app.notifications import due_scheduler as due_scheduler_mod
    from app.notifications import service as notif_service_mod

    monkeypatch.setattr(notif_service_mod, "SessionLocal", TestSession, raising=True)
    monkeypatch.setattr(due_scheduler_mod, "SessionLocal", TestSession, raising=True)

    # Rebind for the auth/user CLI modules — both grab SessionLocal at
    # import time, so the test factory has to be patched on the module
    # itself, not just app.db.
    from app.users import set_password as set_password_mod

    monkeypatch.setattr(set_password_mod, "SessionLocal", TestSession, raising=True)

    from app.knowledge import identity as identity_mod

    monkeypatch.setattr(identity_mod, "SessionLocal", TestSession, raising=True)

    from app.auth import router as auth_router_mod

    monkeypatch.setattr(auth_router_mod, "SessionLocal", TestSession, raising=True)

    try:
        yield TestSession
    finally:
        # Tests get a fresh sqlite file each run so a successful
        # drop_all isn't strictly necessary, but the cyclic FK between
        # `sessions` and `tasks` (and the FKs that hang off them) make
        # the default sort unreliable when other table dependencies are
        # added on top. Turn off FK enforcement on the live connection
        # for the drop sweep so SA can tear the schema down in any
        # order without tripping over half-dropped reference graphs.
        with test_engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            Base.metadata.drop_all(bind=conn)
        test_engine.dispose()


@pytest.fixture
def client(_test_db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        # The conftest seeds the user with password "test-pass". Most tests
        # exercise authenticated endpoints, so log in once and let TestClient's
        # cookie jar carry the session for the rest of the test.
        r = c.post("/api/auth/login", json={"password": "test-pass"})
        assert r.status_code == 200, r.text
        yield c


@pytest.fixture
def unauthed_client(_test_db):
    """TestClient without a session cookie — for tests that need to assert
    401 behaviour or exercise the login flow themselves."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def db_session(_test_db):
    """Open session for tests that talk to the DB directly (no HTTP)."""
    session = _test_db()
    try:
        yield session
    finally:
        session.close()
