from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (REPO / relative).read_text(encoding="utf-8")


def test_systemd_units_run_as_root() -> None:
    for relative in (
        "deploy/life-assistant.service",
        "deploy/life-assistant-update.service",
        "deploy/life-assistant-backup.service",
    ):
        text = _read(relative)
        assert "User=life-assistant" not in text
        assert "Group=life-assistant" not in text


def test_deploy_scripts_do_not_depend_on_service_user_or_sudoers() -> None:
    combined = "\n".join(
        _read(relative)
        for relative in (
            "deploy/install.sh",
            "deploy/update.sh",
            "deploy/backup.sh",
            "deploy/certbot-deploy.sh",
        )
    )
    assert "sudo -u life-assistant" not in combined
    assert "/home/life-assistant" not in combined
    assert "sudoers.life-assistant" not in combined
    assert "/root/.local/bin/uv" in _read("deploy/install.sh")
    assert "/root/.local/bin/uv" in _read("deploy/update.sh")


def test_self_update_skill_starts_update_service_directly() -> None:
    text = _read("backend/defaults/skills/self-update/SKILL.md")
    assert "/usr/bin/systemctl start life-assistant-update.service" in text
    assert "sudo" not in text
