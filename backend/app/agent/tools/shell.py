"""Raw shell tool for the agent — openclaw-style.

`bash` runs commands as a host subprocess with cwd pinned to the repo
root. No sandbox. No allowlist. Output buffered, capped at 30k chars
per stream, killed at the timeout.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

from pydantic_ai import Agent

from app.agent.deps import AgentDeps
from app.agent.tools._task_scope import only_in_task_chat
from app.config import REPO_ROOT

MAX_OUTPUT_CHARS = 30_000


def _truncate(s: str) -> tuple[str, bool]:
    if len(s) <= MAX_OUTPUT_CHARS:
        return s, False
    return s[-MAX_OUTPUT_CHARS:], True


def do_bash(command: str, timeout: int = 120) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        out, out_trunc = _truncate(stdout)
        err, err_trunc = _truncate(stderr)
        return {
            "stdout": out,
            "stderr": err,
            "exit_code": None,
            "truncated": out_trunc or err_trunc,
            "timed_out": True,
        }

    out, out_trunc = _truncate(proc.stdout)
    err, err_trunc = _truncate(proc.stderr)
    return {
        "stdout": out,
        "stderr": err,
        "exit_code": proc.returncode,
        "truncated": out_trunc or err_trunc,
        "timed_out": False,
    }


def register(agent: Agent[AgentDeps, Any]) -> None:
    @agent.tool_plain(prepare=only_in_task_chat)
    def bash(command: str, timeout: int = 120) -> dict[str, Any]:
        """Run a shell command. Cwd is the repo root. No sandbox.

        Returns `{stdout, stderr, exit_code, truncated, timed_out}`.
        Each of stdout/stderr is capped at 30000 chars (tail kept).
        On timeout, exit_code is null and partial buffers are returned.

        Don't touch `data/*.db*` — that's the live SQLite store
        (corruption loses all tasks/chats). For knowledge entries
        use `save_knowledge`; for core memory use `save_core_memory`.
        """
        return do_bash(command, timeout=timeout)
