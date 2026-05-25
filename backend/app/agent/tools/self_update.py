"""Self-update tool - triggers `life-assistant-update.service` over systemd.

Fires the oneshot updater (git pull, build, restart Life Assistant). The current
process is killed by `systemctl restart life-assistant.service` partway through;
in-flight task sessions resume on the next process via the watchdog
recovery in `app.main` lifespan startup.

No-op outside systemd (when `INVOCATION_ID` is unset) so dev `make dev`
can't accidentally restart itself.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

from pydantic_ai import Agent

from app.agent.deps import AgentDeps

UPDATE_CMD = ["sudo", "/usr/bin/systemctl", "start", "life-assistant-update.service"]


def do_self_update() -> dict[str, Any]:
    if not os.environ.get("INVOCATION_ID"):
        return {
            "ok": False,
            "reason": "not running under systemd; refusing to self-update from dev",
        }
    try:
        proc = subprocess.run(
            UPDATE_CMD,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {"ok": False, "reason": f"systemctl call failed: {exc}"}

    if proc.returncode != 0:
        return {
            "ok": False,
            "reason": f"systemctl exited {proc.returncode}",
            "stderr": proc.stderr.strip(),
        }
    return {
        "ok": True,
        "message": "update started; Life Assistant will restart shortly",
    }


def register(agent: Agent[AgentDeps, Any]) -> None:
    @agent.tool_plain
    def self_update() -> dict[str, Any]:
        """Pull the latest main, rebuild, and restart Life Assistant on the VPS.

        Use this when the user asks to "deploy", "update", or "ship the
        latest". Returns immediately — the actual update runs in a
        separate systemd oneshot. Life Assistant will be unreachable for ~30-60s
        while it rebuilds and restarts. In-flight autonomous tasks
        survive the restart (watchdog re-wakes them).

        Returns `{ok, message}` on success, `{ok: false, reason}` if
        not running under systemd or if systemctl rejected the call.
        """
        return do_self_update()
