#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "typer>=0.12",
#   "questionary>=2.0",
#   "rich>=13",
# ]
# ///
"""Life Assistant worktree + cmux workspace lifecycle.

Subcommands:
    wtree                   interactive menu (start | stop | list)
    wtree start [BRANCH]    create worktree + cmux workspace
    wtree stop  [BRANCH]    tear down worktree + close workspace
    wtree list              show all live worktrees

Each created cmux workspace has four named horizontal tabs:
    claude   — Claude Code agent
    dev      — `make dev` (backend + frontend on isolated ports)
    shell    — free shell for tests / git / one-offs
    preview  — embedded browser at the worktree's frontend port

State per worktree is persisted in `<worktree>/.wtree.json` so we never
have to scrape cmux text output to find IDs.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import questionary
import typer
from rich.console import Console
from rich.table import Table

CMUX = "/Applications/cmux.app/Contents/Resources/bin/cmux"
WORKSPACE_PREFIX = "life:"
TAB_NAMES = ["claude", "dev", "shell", "preview"]

# Status sentinel values written to <wt>/.wtree-status. Claude is told
# (via --append-system-prompt) to `cat .wtree-status` before running
# anything that touches deps.
STATUS_INSTALLING = "installing"
STATUS_READY = "ready"
STATUS_FAILED = "failed"

CLAUDE_SYSTEM_NOTE = """\
You're running inside a cmux workspace opened by scripts/wtree.py for a \
fresh Life Assistant worktree. The workspace has these sibling tabs:
- dev     runs .wtree-bootstrap.sh, which installs deps and then execs `make dev`
- shell   empty shell for ad-hoc work
- preview embedded browser at the worktree's frontend URL

Worktree-local state (read on demand from cwd):
- .wtree-status   one of `installing` / `ready` / `failed`
- .env            per-branch overrides only (BACKEND_PORT, FRONTEND_PORT,
                   SESSION_SECRET). Shared secrets (provider keys,
                   LANGFUSE_*, …) live in ~/.config/life-assistant/.env and are read
                   by app.config directly — not copied per worktree.

Until `.wtree-status` reads `ready`, the env is not yet provisioned: \
backend, frontend, alembic, pytest, and vitest will fail on missing deps. \
Check `.wtree-status` before running anything that touches them.

Never start `make dev` here — the dev tab owns it; a second copy fights \
for the same ports. If `.wtree-status` is `failed`, surface it to the \
user instead of silently retrying the bootstrap."""

console = Console()
app = typer.Typer(
    add_completion=False,
    help="Life Assistant worktree + cmux workspace lifecycle.",
    no_args_is_help=False,
)


# ---------- cmux RPC ---------------------------------------------------------


class CmuxError(RuntimeError):
    pass


def cmux_rpc(method: str, **params: Any) -> dict[str, Any]:
    """Call a cmux RPC method, return parsed JSON. Raises on failure."""
    if not Path(CMUX).exists():
        raise CmuxError(f"cmux binary missing at {CMUX}")
    payload = json.dumps(params) if params else "{}"
    proc = subprocess.run(
        [CMUX, "rpc", method, payload],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise CmuxError(f"{method} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    out = proc.stdout.strip()
    if not out:
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise CmuxError(f"{method} returned non-JSON: {out[:200]}") from e


def cmux_available() -> bool:
    return Path(CMUX).exists()


# ---------- repo + worktree helpers -----------------------------------------


def repo_root() -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(proc.stdout.strip())


def wt_root(repo: Path) -> Path:
    return repo.parent / f"{repo.name}-wt"


def worktree_path(repo: Path, branch: str) -> Path:
    return wt_root(repo) / branch


def alloc_ports(branch: str) -> tuple[int, int]:
    """Stable, branch-derived port pair so two worktrees never collide."""
    h = int(hashlib.sha256(branch.encode()).hexdigest()[:4], 16) % 900
    return 8000 + h, 5173 + h


def list_local_worktrees() -> list[str]:
    """Return branch names that have a wtree directory."""
    repo = repo_root()
    root = wt_root(repo)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


@dataclass
class Meta:
    """Persisted state per worktree, stored at <wt>/.wtree.json."""

    branch: str
    backend_port: int
    frontend_port: int
    workspace_id: str | None = None
    surfaces: dict[str, str] | None = None  # tab name -> surface_id

    @classmethod
    def load(cls, wt: Path) -> "Meta | None":
        f = wt / ".wtree.json"
        if not f.exists():
            return None
        return cls(**json.loads(f.read_text()))

    def save(self, wt: Path) -> None:
        (wt / ".wtree.json").write_text(json.dumps(self.__dict__, indent=2))


# ---------- setup steps -----------------------------------------------------


def carry_dirty_files(repo: Path, wt: Path) -> None:
    """Copy files with uncommitted edits in main into the new worktree.

    The worktree branches off HEAD, so any unstaged edits in main are
    invisible there otherwise — which silently breaks anything that
    depends on them (e.g. the Makefile port flags).
    """
    proc = subprocess.run(
        ["git", "-C", str(repo), "diff", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    for line in proc.stdout.splitlines():
        if not line:
            continue
        src = repo / line
        if not src.is_file():
            continue
        dst = wt / line
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def write_env_overrides(wt: Path, branch: str, backend: int, frontend: int) -> None:
    import secrets

    env_file = wt / ".env"
    existing = env_file.read_text() if env_file.exists() else ""
    with env_file.open("a") as f:
        f.write(f"\n# --- wtree overrides ({branch}) ---\n")
        f.write(f"BACKEND_PORT={backend}\n")
        f.write(f"FRONTEND_PORT={frontend}\n")
        if "SESSION_SECRET=" not in existing:
            f.write(f"SESSION_SECRET={secrets.token_hex(32)}\n")


def write_bootstrap_artifacts(wt: Path, branch: str, backend: int, frontend: int) -> None:
    """Drop the status file, the README, and the bootstrap script that
    the dev tab will execute. Doing this before opening cmux means
    claude can read WTREE_BOOTSTRAP.md from the moment its tab opens.
    """
    (wt / ".wtree-status").write_text(STATUS_INSTALLING + "\n")

    (wt / "WTREE_BOOTSTRAP.md").write_text(
        f"""# Worktree bootstrap

Branch:   `{branch}`
Backend:  http://localhost:{backend}
Frontend: http://localhost:{frontend}/chat

## Status protocol

`./.wtree-status` holds one of:
- `{STATUS_INSTALLING}` — `uv sync` / `alembic upgrade` / `pnpm install` still running
- `{STATUS_READY}` — env is up; `make dev` is now running in the dev tab
- `{STATUS_FAILED}` — bootstrap blew up; read the dev tab for the error

Claude: check `cat .wtree-status` before any `pytest`, `pnpm test`,
`make dev`, or other dep-dependent commands. Until it reads `{STATUS_READY}`,
those will fail.

## Tabs

1. **claude** — agent (this one)
2. **dev**    — runs `.wtree-bootstrap.sh`: installs deps, then execs `make dev`
3. **shell**  — free shell for ad-hoc commands
4. **preview**— embedded browser at the frontend URL above
"""
    )

    bootstrap = wt / ".wtree-bootstrap.sh"
    bootstrap.write_text(
        f"""#!/usr/bin/env bash
# Auto-generated by scripts/wtree.py. Runs in the worktree's dev tab.
set -euo pipefail
cd "$(dirname "$0")"

mark() {{ echo "$1" > .wtree-status; }}
trap 'mark {STATUS_FAILED}' ERR

echo "[wtree] {branch}: installing deps (parallel)…"
( cd backend && uv sync ) &
uv_pid=$!
( cd frontend && pnpm install ) &
pnpm_pid=$!
wait $uv_pid
wait $pnpm_pid

echo "[wtree] {branch}: applying alembic migrations…"
( cd backend && uv run alembic upgrade head )

echo "[wtree] {branch}: seeding dev login password…"
( cd backend && uv run python -m app.users.set_password dev )

mark {STATUS_READY}
echo "[wtree] {branch}: ready. Launching make dev…"
set -a; source .env; set +a
exec make dev
"""
    )
    bootstrap.chmod(0o755)


# ---------- cmux workspace orchestration ------------------------------------


def _shell_quote(s: str) -> str:
    """Wrap text so the shell preserves it verbatim when interpolated."""
    return "'" + s.replace("'", "'\\''") + "'"


def _surface_run(surface_id: str, command: str) -> None:
    """Type a command into a cmux terminal surface and press Enter.

    cmux's RPC does not accept a 'command' arg on workspace.create or
    surface.create — those args are silently ignored. The CLI tool
    fakes it by send_text+send_key, so we do the same.
    """
    cmux_rpc("surface.send_text", surface_id=surface_id, text=command)
    cmux_rpc("surface.send_key", surface_id=surface_id, key="Enter")


def create_workspace(branch: str, wt: Path, frontend_port: int) -> tuple[str, dict[str, str]]:
    """Create the cmux workspace + four named tabs.

    Sequence:
    1. Empty workspace at the worktree path (auto-creates one shell surface).
    2. Rename it to `life:<branch>` (workspace.create ignores the name arg).
    3. Type `claude --append-system-prompt …` into the auto-shell so the
       agent boots oriented to where it is.
    4. Create dev/shell/preview surfaces and run the bootstrap in dev.
    5. Rename each tab via tab.action.
    """
    ws = cmux_rpc("workspace.create", cwd=str(wt))
    workspace_id = ws["workspace_id"]

    cmux_rpc(
        "workspace.rename",
        workspace_id=workspace_id,
        title=f"{WORKSPACE_PREFIX}{branch}",
    )

    surfaces_resp = cmux_rpc("surface.list", workspace_id=workspace_id)
    claude_surface = surfaces_resp["surfaces"][0]["id"]
    _surface_run(
        claude_surface,
        f"claude --append-system-prompt {_shell_quote(CLAUDE_SYSTEM_NOTE)}",
    )

    dev = cmux_rpc("surface.create", workspace_id=workspace_id, type="terminal")
    dev_surface = dev["surface_id"]
    _surface_run(dev_surface, "bash .wtree-bootstrap.sh")

    sh = cmux_rpc("surface.create", workspace_id=workspace_id, type="terminal")
    shell_surface = sh["surface_id"]

    pv = cmux_rpc(
        "surface.create",
        workspace_id=workspace_id,
        type="browser",
        url=f"http://localhost:{frontend_port}/chat",
    )
    preview_surface = pv["surface_id"]

    surfaces = {
        "claude": claude_surface,
        "dev": dev_surface,
        "shell": shell_surface,
        "preview": preview_surface,
    }
    for title, sid in surfaces.items():
        try:
            cmux_rpc("tab.action", action="rename", surface_id=sid, title=title)
        except CmuxError as e:
            console.print(f"[yellow]rename {title}: {e}[/yellow]")

    return workspace_id, surfaces


def close_workspace(workspace_id: str) -> None:
    try:
        cmux_rpc("workspace.close", workspace_id=workspace_id)
    except CmuxError as e:
        console.print(f"[yellow]workspace.close: {e}[/yellow]")


# ---------- subcommands -----------------------------------------------------


def _do_start(branch: str) -> None:
    repo = repo_root()
    wt = worktree_path(repo, branch)
    if wt.exists():
        console.print(f"[red]worktree already exists: {wt}[/red]")
        raise typer.Exit(1)

    backend_port, frontend_port = alloc_ports(branch)

    with console.status(f"creating worktree {wt}"):
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "add", str(wt), "-b", branch],
            check=True,
            capture_output=True,
        )
        # No .env copy: secrets come from the shared machine-level file
        # (~/.config/life-assistant/.env, see app.config.SHARED_ENV). wt/.env holds
        # only the per-branch overrides written just below.
        carry_dirty_files(repo, wt)
        write_env_overrides(wt, branch, backend_port, frontend_port)
        write_bootstrap_artifacts(wt, branch, backend_port, frontend_port)

    console.print(f"  worktree at [cyan]{wt}[/cyan]")
    console.print(
        f"  ports backend=[cyan]:{backend_port}[/cyan] frontend=[cyan]:{frontend_port}[/cyan]"
    )

    meta = Meta(branch=branch, backend_port=backend_port, frontend_port=frontend_port)

    # Open the cmux UI before deps install — the dev tab runs the
    # bootstrap script visibly so the user (and claude, via
    # `cat .wtree-status`) can watch it work.
    if cmux_available():
        with console.status(f"opening cmux workspace [bold]{WORKSPACE_PREFIX}{branch}[/bold]"):
            ws_id, surfaces = create_workspace(branch, wt, frontend_port)
        meta.workspace_id = ws_id
        meta.surfaces = surfaces
        console.print(f"  cmux workspace [cyan]{ws_id[:8]}…[/cyan] tabs: {', '.join(TAB_NAMES)}")
        console.print(
            "  [dim]bootstrap (uv sync + pnpm install + alembic) running "
            "in the dev tab; status in [bold].wtree-status[/bold].[/dim]"
        )
    else:
        console.print("[yellow]cmux not found — run `bash .wtree-bootstrap.sh` manually.[/yellow]")

    meta.save(wt)
    console.print(f"[green]✓ life:{branch} launched[/green]")


def _do_stop(branch: str) -> None:
    repo = repo_root()
    wt = worktree_path(repo, branch)

    meta = Meta.load(wt) if wt.exists() else None

    if meta and meta.workspace_id and cmux_available():
        with console.status("closing cmux workspace"):
            close_workspace(meta.workspace_id)

    with console.status(f"removing worktree {wt}"):
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", "--force", str(wt)],
            capture_output=True,
        )
        if wt.exists():
            shutil.rmtree(wt, ignore_errors=True)
        subprocess.run(
            ["git", "-C", str(repo), "branch", "-D", branch],
            capture_output=True,
        )

    console.print(f"[green]✓ life:{branch} removed[/green]")


def _do_list() -> None:
    branches = list_local_worktrees()
    if not branches:
        console.print("[dim](no worktrees)[/dim]")
        return
    table = Table(title="Life Assistant worktrees")
    table.add_column("branch", style="cyan")
    table.add_column("backend")
    table.add_column("frontend")
    table.add_column("workspace")
    repo = repo_root()
    for b in branches:
        meta = Meta.load(worktree_path(repo, b))
        if meta is None:
            backend, frontend = alloc_ports(b)
            ws = "—"
        else:
            backend, frontend = meta.backend_port, meta.frontend_port
            ws = (meta.workspace_id or "—")[:8] + "…" if meta.workspace_id else "—"
        table.add_row(b, f":{backend}", f":{frontend}", ws)
    console.print(table)


# ---------- typer entry points ----------------------------------------------


@app.command()
def start(branch: str = typer.Argument(None, help="Branch name to create")) -> None:
    """Create a worktree + cmux workspace for BRANCH (prompts if omitted)."""
    if not branch:
        branch = (questionary.text("Branch name").ask() or "").strip()
    if not branch:
        console.print("[red]empty branch[/red]")
        raise typer.Exit(1)
    _do_start(branch)


@app.command(name="stop")
def stop(branch: str = typer.Argument(None, help="Branch to remove")) -> None:
    """Tear down a worktree + close its cmux workspace (prompts if omitted)."""
    if not branch:
        existing = list_local_worktrees()
        if not existing:
            console.print("[dim](no worktrees to stop)[/dim]")
            raise typer.Exit(0)
        branch = questionary.select("Stop which worktree?", choices=existing).ask()
        if not branch:
            raise typer.Exit(0)
        if not questionary.confirm(
            f"Remove worktree '{branch}' and its branch?", default=False
        ).ask():
            console.print("[dim]cancelled[/dim]")
            raise typer.Exit(0)
    _do_stop(branch)


@app.command(name="list")
def list_() -> None:
    """Show all live worktrees with their port + workspace IDs."""
    _do_list()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Default to interactive menu when no subcommand given."""
    if ctx.invoked_subcommand is not None:
        return
    choice = questionary.select("wtree", choices=["start", "stop", "list", "quit"]).ask()
    if choice == "start":
        start(None)  # type: ignore[arg-type]
    elif choice == "stop":
        stop(None)  # type: ignore[arg-type]
    elif choice == "list":
        list_()


if __name__ == "__main__":
    app()
