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
    wtree slot ...          manage six fixed PyCharm-friendly slots

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
FIXED_SLOT_COUNT = 6
FIXED_SLOT_BRANCH_PREFIX = "worktree/slot"
FIXED_SLOT_BACKEND_BASE = 8020
FIXED_SLOT_FRONTEND_BASE = 5180
FIXED_SLOT_ENV_BEGIN = "# --- wtree fixed-slot managed block ---"
FIXED_SLOT_ENV_END = "# --- end wtree fixed-slot managed block ---"
PYCHARM_APP = "/Applications/PyCharm.app"

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
slot_app = typer.Typer(
    add_completion=False,
    help="Manage six fixed PyCharm-friendly worktree slots.",
)
app.add_typer(slot_app, name="slot")


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
        raise CmuxError(
            f"{method} failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
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


def remote_repo_name(repo: Path) -> str:
    """Return the origin repo name, so temp worktrees still target stable slot dirs."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "config", "--get", "remote.origin.url"],
        capture_output=True,
        text=True,
        check=False,
    )
    remote = proc.stdout.strip()
    if not remote:
        return repo.name
    name = remote.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name or repo.name


def fixed_slots_root(repo: Path) -> Path:
    """Use the conventional ~/Projects path for fixed local slots when possible."""
    candidate = Path.home() / "Projects"
    if (
        candidate.exists()
        and str(candidate.resolve()).lower() == str(repo.parent.resolve()).lower()
    ):
        return candidate
    return repo.parent


def wt_root(repo: Path) -> Path:
    return repo.parent / f"{repo.name}-wt"


def worktree_path(repo: Path, branch: str) -> Path:
    return wt_root(repo) / branch


def fixed_slot_path(repo: Path, slot: int) -> Path:
    return fixed_slots_root(repo) / f"{remote_repo_name(repo)}-slot-{slot}"


def fixed_slot_branch(slot: int) -> str:
    return f"{FIXED_SLOT_BRANCH_PREFIX}-{slot}"


def fixed_slot_ports(slot: int) -> tuple[int, int]:
    return FIXED_SLOT_BACKEND_BASE + slot - 1, FIXED_SLOT_FRONTEND_BASE + slot - 1


def projects_bin_dir(repo: Path) -> Path:
    return fixed_slots_root(repo) / "bin"


def projects_env_sh(repo: Path) -> Path:
    return fixed_slots_root(repo) / "env.sh"


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


def write_bootstrap_artifacts(
    wt: Path, branch: str, backend: int, frontend: int
) -> None:
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


# ---------- fixed slot helpers ---------------------------------------------


def _slot_numbers(target: str) -> list[int]:
    target = target.strip().lower()
    if target == "all":
        return list(range(1, FIXED_SLOT_COUNT + 1))
    try:
        slot = int(target)
    except ValueError:
        console.print(
            f"[red]slot must be 1-{FIXED_SLOT_COUNT} or 'all': {target}[/red]"
        )
        raise typer.Exit(2)
    if slot < 1 or slot > FIXED_SLOT_COUNT:
        console.print(f"[red]slot must be 1-{FIXED_SLOT_COUNT}: {slot}[/red]")
        raise typer.Exit(2)
    return [slot]


def _git_ref_exists(repo: Path, ref: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", ref],
            capture_output=True,
        ).returncode
        == 0
    )


def _git_branch_exists(repo: Path, branch: str) -> bool:
    return (
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/{branch}",
            ]
        ).returncode
        == 0
    )


def _refresh_origin_main(repo: Path) -> None:
    proc = subprocess.run(
        ["git", "-C", str(repo), "fetch", "origin", "main:refs/remotes/origin/main"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        console.print(
            "[yellow]could not refresh origin/main; using local origin/main[/yellow]"
        )
        if proc.stderr.strip():
            console.print(f"[dim]{proc.stderr.strip()}[/dim]")
    if not _git_ref_exists(repo, "origin/main"):
        console.print("[red]origin/main is not available[/red]")
        raise typer.Exit(1)


def _is_git_worktree(path: Path) -> bool:
    return (
        path.exists()
        and subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )


def _current_branch(path: Path) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(path), "branch", "--show-current"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _env_value(text: str, key: str) -> str | None:
    prefix = f"{key}="
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :]
    return None


def _strip_managed_env_block(text: str) -> str:
    lines: list[str] = []
    in_block = False
    for line in text.splitlines():
        if line.strip() == FIXED_SLOT_ENV_BEGIN:
            in_block = True
            continue
        if line.strip() == FIXED_SLOT_ENV_END:
            in_block = False
            continue
        if not in_block:
            lines.append(line)
    return "\n".join(lines).rstrip()


def write_fixed_slot_env(wt: Path, slot: int) -> None:
    import secrets

    backend_port, frontend_port = fixed_slot_ports(slot)
    env_file = wt / ".env"
    existing = env_file.read_text() if env_file.exists() else ""
    session_secret = _env_value(existing, "SESSION_SECRET") or secrets.token_hex(32)
    custom = _strip_managed_env_block(existing)
    db_path = wt / "data" / "life_assistant.db"
    managed = "\n".join(
        [
            FIXED_SLOT_ENV_BEGIN,
            "ENV=dev",
            "SERVE_FRONTEND=false",
            f"BACKEND_PORT={backend_port}",
            f"FRONTEND_PORT={frontend_port}",
            f"DATABASE_URL=sqlite:///{db_path}",
            f"SESSION_SECRET={session_secret}",
            FIXED_SLOT_ENV_END,
        ]
    )
    env_file.write_text(f"{custom}\n\n{managed}\n" if custom else f"{managed}\n")


def _launcher_path(repo: Path, slot: int, command: str) -> Path:
    return projects_bin_dir(repo) / f"{remote_repo_name(repo)}-slot-{slot}-{command}"


def _launcher_header(repo: Path, wt: Path) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

SLOT_DIR="{wt}"
ENV_SH="{projects_env_sh(repo)}"
PYCHARM_APP="{PYCHARM_APP}"

load_slot_env() {{
  if [ -f "$ENV_SH" ]; then
    # shellcheck disable=SC1090
    source "$ENV_SH"
  fi
  if [ -f "$SLOT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$SLOT_DIR/.env"
    set +a
  fi
}}

"""


def write_fixed_slot_launchers(repo: Path, slot: int) -> None:
    wt = fixed_slot_path(repo, slot)
    bin_dir = projects_bin_dir(repo)
    bin_dir.mkdir(parents=True, exist_ok=True)
    scripts = {
        "pycharm": f"""{_launcher_header(repo, wt)}exec open -na "$PYCHARM_APP" --args "$SLOT_DIR"
""",
        "setup": f"""{_launcher_header(repo, wt)}load_slot_env
cd "$SLOT_DIR/backend"
uv sync
cd "$SLOT_DIR/frontend"
pnpm install --frozen-lockfile
cd "$SLOT_DIR/backend"
uv run alembic upgrade head
uv run python -m app.users.set_password dev
""",
        "dev": f"""{_launcher_header(repo, wt)}load_slot_env
cd "$SLOT_DIR"
exec make dev "$@"
""",
        "backend": f"""{_launcher_header(repo, wt)}load_slot_env
cd "$SLOT_DIR"
exec make backend "$@"
""",
        "frontend": f"""{_launcher_header(repo, wt)}load_slot_env
cd "$SLOT_DIR"
exec make frontend "$@"
""",
    }
    for command, body in scripts.items():
        target = _launcher_path(repo, slot, command)
        target.write_text(body)
        target.chmod(0o755)


def ensure_fixed_slot(repo: Path, slot: int) -> None:
    wt = fixed_slot_path(repo, slot)
    branch = fixed_slot_branch(slot)

    if wt.exists() and not _is_git_worktree(wt):
        console.print(f"[red]{wt} exists but is not a git worktree[/red]")
        raise typer.Exit(1)

    if not wt.exists():
        if _git_branch_exists(repo, branch):
            args = ["git", "-C", str(repo), "worktree", "add", str(wt), branch]
        else:
            args = [
                "git",
                "-C",
                str(repo),
                "worktree",
                "add",
                "-b",
                branch,
                str(wt),
                "origin/main",
            ]
        subprocess.run(args, check=True)

    current = _current_branch(wt)
    if current != branch:
        console.print(
            f"[red]{wt} is on {current or 'detached HEAD'}, expected {branch}[/red]"
        )
        raise typer.Exit(1)

    write_fixed_slot_env(wt, slot)
    write_fixed_slot_launchers(repo, slot)


def _run_launcher(repo: Path, slot: int, command: str) -> None:
    launcher = _launcher_path(repo, slot, command)
    if not launcher.exists():
        ensure_fixed_slot(repo, slot)
    subprocess.run([str(launcher)], check=True)


def _slot_setup_status(repo: Path, slot: int) -> str:
    wt = fixed_slot_path(repo, slot)
    if not wt.exists():
        return "missing"
    if not _is_git_worktree(wt):
        return "not-git"
    env_ok = (wt / ".env").is_file()
    backend_ok = (wt / "backend" / ".venv").is_dir()
    frontend_ok = (wt / "frontend" / "node_modules").is_dir()
    if env_ok and backend_ok and frontend_ok:
        return "setup"
    if env_ok:
        return "initialized"
    return "no-env"


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


def create_workspace(
    branch: str, wt: Path, frontend_port: int
) -> tuple[str, dict[str, str]]:
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
        with console.status(
            f"opening cmux workspace [bold]{WORKSPACE_PREFIX}{branch}[/bold]"
        ):
            ws_id, surfaces = create_workspace(branch, wt, frontend_port)
        meta.workspace_id = ws_id
        meta.surfaces = surfaces
        console.print(
            f"  cmux workspace [cyan]{ws_id[:8]}…[/cyan] tabs: {', '.join(TAB_NAMES)}"
        )
        console.print(
            "  [dim]bootstrap (uv sync + pnpm install + alembic) running "
            "in the dev tab; status in [bold].wtree-status[/bold].[/dim]"
        )
    else:
        console.print(
            "[yellow]cmux not found — run `bash .wtree-bootstrap.sh` manually.[/yellow]"
        )

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


# ---------- fixed slot entry points -----------------------------------------


@slot_app.command(name="init")
def slot_init(
    target: str = typer.Argument("all", help="Slot number 1-6, or 'all'"),
) -> None:
    """Create/update fixed slot worktrees, env files, and local launchers."""
    repo = repo_root()
    slots = _slot_numbers(target)
    _refresh_origin_main(repo)
    for slot in slots:
        ensure_fixed_slot(repo, slot)
        wt = fixed_slot_path(repo, slot)
        backend_port, frontend_port = fixed_slot_ports(slot)
        console.print(
            f"[green]slot {slot}[/green] {wt} "
            f"backend=:{backend_port} frontend=:{frontend_port}"
        )


@slot_app.command(name="list")
def slot_list() -> None:
    """Show fixed slot paths, branches, ports, and setup status."""
    repo = repo_root()
    table = Table(title="Life Assistant fixed slots")
    table.add_column("slot", style="cyan")
    table.add_column("branch")
    table.add_column("backend")
    table.add_column("frontend")
    table.add_column("status")
    table.add_column("path")
    for slot in range(1, FIXED_SLOT_COUNT + 1):
        backend_port, frontend_port = fixed_slot_ports(slot)
        table.add_row(
            str(slot),
            fixed_slot_branch(slot),
            f":{backend_port}",
            f":{frontend_port}",
            _slot_setup_status(repo, slot),
            str(fixed_slot_path(repo, slot)),
        )
    console.print(table)


@slot_app.command(name="setup")
def slot_setup(
    target: str = typer.Argument("all", help="Slot number 1-6, or 'all'"),
) -> None:
    """Install backend/frontend deps, migrate SQLite, and seed dev password."""
    repo = repo_root()
    slots = _slot_numbers(target)
    _refresh_origin_main(repo)
    for slot in slots:
        ensure_fixed_slot(repo, slot)
        console.print(f"[cyan]setting up slot {slot}[/cyan]")
        _run_launcher(repo, slot, "setup")


@slot_app.command(name="dev")
def slot_dev(slot: int = typer.Argument(..., help="Slot number 1-6")) -> None:
    """Run `make dev` for a fixed slot."""
    repo = repo_root()
    _slot_numbers(str(slot))
    ensure_fixed_slot(repo, slot)
    _run_launcher(repo, slot, "dev")


@slot_app.command(name="backend")
def slot_backend(slot: int = typer.Argument(..., help="Slot number 1-6")) -> None:
    """Run `make backend` for a fixed slot."""
    repo = repo_root()
    _slot_numbers(str(slot))
    ensure_fixed_slot(repo, slot)
    _run_launcher(repo, slot, "backend")


@slot_app.command(name="frontend")
def slot_frontend(slot: int = typer.Argument(..., help="Slot number 1-6")) -> None:
    """Run `make frontend` for a fixed slot."""
    repo = repo_root()
    _slot_numbers(str(slot))
    ensure_fixed_slot(repo, slot)
    _run_launcher(repo, slot, "frontend")


@slot_app.command(name="open")
def slot_open(slot: int = typer.Argument(..., help="Slot number 1-6")) -> None:
    """Open a fixed slot in PyCharm."""
    repo = repo_root()
    _slot_numbers(str(slot))
    ensure_fixed_slot(repo, slot)
    _run_launcher(repo, slot, "pycharm")


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
    choice = questionary.select(
        "wtree", choices=["start", "stop", "list", "quit"]
    ).ask()
    if choice == "start":
        start(None)  # type: ignore[arg-type]
    elif choice == "stop":
        stop(None)  # type: ignore[arg-type]
    elif choice == "list":
        list_()


if __name__ == "__main__":
    app()
