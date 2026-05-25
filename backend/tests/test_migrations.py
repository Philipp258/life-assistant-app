"""Alembic guardrails. CI applies migrations on a fresh DB; this catches
the cheap-to-prevent regressions before that runs.

The 43-migration chain was squashed into a single `0001_baseline`
(see `alembic/versions/0001_baseline.py`). Schema fidelity vs. the old
chain is asserted in `test_baseline_schema.py`."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND = Path(__file__).resolve().parents[1]


def _scripts() -> ScriptDirectory:
    cfg = Config(str(_BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND / "alembic"))
    return ScriptDirectory.from_config(cfg)


def test_alembic_single_head():
    heads = _scripts().get_heads()
    assert len(heads) == 1, f"expected a single migration head, got {heads}"


def test_baseline_is_the_chain_floor():
    """Post-squash, 0001_baseline is the single base with no
    down_revision. New migrations stack on top of it (single linear
    chain, one head); a resurrected pre-squash file would create a
    second base or an unresolvable down_revision and break this."""
    scripts = _scripts()
    assert scripts.get_bases() == ["0001_baseline"]
    assert scripts.get_revision("0001_baseline").down_revision is None
    assert len(scripts.get_heads()) == 1
