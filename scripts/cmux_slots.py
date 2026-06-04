#!/usr/bin/env python3
"""Manage cmux workspaces and on-demand app startup for fixed Life Assistant slots."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

CMUX = Path("/Applications/cmux.app/Contents/Resources/bin/cmux")
CMUX_APP = "/Applications/cmux.app"
PROJECTS_DIR = Path.home() / "Projects"
REPO_NAME = "life-assistant-app"
SLOT_COUNT = 6
BACKEND_BASE = 8020
FRONTEND_BASE = 5180
STATE_FILE = Path.home() / ".config" / "life-assistant" / "cmux-slots.json"


class CmuxSlotsError(RuntimeError):
    pass


def run(
    args: list[str], *, check: bool = True, capture: bool = True
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("CMUX_QUIET", "1")
    proc = subprocess.run(
        args,
        capture_output=capture,
        text=True,
        env=env,
    )
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise CmuxSlotsError(f"{shlex.join(args)} failed: {detail}")
    return proc


def cmux_rpc(method: str, **params: Any) -> dict[str, Any]:
    proc = run([str(CMUX), "rpc", method, json.dumps(params)])
    out = proc.stdout.strip()
    if not out:
        return {}
    return json.loads(out)


def cmux_ready() -> bool:
    return run([str(CMUX), "ping"], check=False).returncode == 0


def wait_for_cmux(seconds: float = 8.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if cmux_ready():
            return True
        time.sleep(0.25)
    return cmux_ready()


def ensure_cmux(*, restart: bool) -> None:
    if cmux_ready():
        return
    if restart:
        run(["osascript", "-e", 'quit app "cmux"'], check=False)
        time.sleep(1)
    run(["open", "-a", CMUX_APP], check=False)
    if wait_for_cmux():
        return
    hint = "Try quitting/reopening cmux, or rerun with --restart-cmux."
    if restart:
        hint = "cmux still did not accept socket commands after restart."
    raise CmuxSlotsError(f"cmux socket is not responding. {hint}")


def slot_path(slot: int) -> Path:
    return PROJECTS_DIR / f"{REPO_NAME}-slot-{slot}"


def slot_branch(slot: int) -> str:
    return f"worktree/slot-{slot}"


def frontend_port(slot: int) -> int:
    return FRONTEND_BASE + slot - 1


def backend_port(slot: int) -> int:
    return BACKEND_BASE + slot - 1


def frontend_url(slot: int) -> str:
    return f"http://localhost:{frontend_port(slot)}/chat"


def backend_url(slot: int) -> str:
    return f"http://localhost:{backend_port(slot)}/api/health"


def marker(slot: int) -> str:
    return f"life-assistant-fixed-slot:{slot}"


def default_title(slot: int) -> str:
    return f"life slot {slot}"


def task_title(slot: int, title: str) -> str:
    clean = " ".join(title.split())
    if not clean:
        return default_title(slot)
    return f"life {slot}: {clean}"[:80]


def state_load() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"slots": {}}
    try:
        return json.loads(STATE_FILE.read_text())
    except json.JSONDecodeError:
        return {"slots": {}}


def state_save(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def slot_env_command(slot: int) -> str:
    path = slot_path(slot)
    env_sh = PROJECTS_DIR / "env.sh"
    parts = [
        f"cd {shlex.quote(str(path))}",
        f"[ -f {shlex.quote(str(env_sh))} ] && source {shlex.quote(str(env_sh))}",
        "set -a",
        "source .env",
        "set +a",
    ]
    return "; ".join(parts)


def coding_agent_command(slot: int) -> str:
    agent = os.environ.get("CODING_AGENT_CMD")
    if not agent:
        claude = shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")
        agent = shlex.quote(claude)
    return f"{slot_env_command(slot)}; exec {agent}"


def dev_command(slot: int) -> str:
    setup_hint = f"Run: cd {slot_path(slot)} && make dev, or hydrate this slot first."
    return (
        f"{slot_env_command(slot)}; "
        "if [ ! -d backend/.venv ] || [ ! -d frontend/node_modules ]; then "
        f"echo {shlex.quote(setup_hint)}; exec ${'{'}SHELL:-/bin/zsh{'}'} -l; "
        "fi; "
        "exec make dev"
    )


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def app_status(slot: int) -> str:
    backend = port_open(backend_port(slot))
    frontend = port_open(frontend_port(slot))
    if backend and frontend:
        return "up"
    if backend or frontend:
        return "partial"
    return "down"


def send_command(surface_id: str, command: str) -> None:
    cmux_rpc("surface.send_text", surface_id=surface_id, text=command)
    cmux_rpc("surface.send_key", surface_id=surface_id, key="Enter")


def rename_tab(surface_id: str, title: str) -> None:
    cmux_rpc("tab.action", action="rename", surface_id=surface_id, title=title)


def pin_workspace(workspace_id: str) -> None:
    run(
        [str(CMUX), "workspace-action", "--workspace", workspace_id, "--action", "pin"],
        check=False,
    )


def describe_workspace(workspace_id: str, slot: int) -> None:
    description = "\n".join(
        [
            marker(slot),
            f"path={slot_path(slot)}",
            f"branch={slot_branch(slot)}",
            f"backend=:{backend_port(slot)}",
            f"frontend=:{frontend_port(slot)}",
        ]
    )
    run(
        [
            str(CMUX),
            "workspace-action",
            "--workspace",
            workspace_id,
            "--action",
            "set-description",
            "--description",
            description,
        ],
        check=False,
    )


def list_surfaces(workspace_id: str) -> list[dict[str, Any]]:
    surfaces = cmux_rpc("surface.list", workspace_id=workspace_id).get("surfaces", [])
    return [surface for surface in surfaces if isinstance(surface, dict)]


def surface_id(surface: dict[str, Any]) -> str | None:
    for key in ("id", "surface_id", "surfaceId", "uuid", "ref", "handle"):
        value = surface.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def find_surface(workspace_id: str, title: str) -> str | None:
    for surface in list_surfaces(workspace_id):
        if title in json.dumps(surface, sort_keys=True):
            found = surface_id(surface)
            if found:
                return found
    return None


def create_surface(
    workspace_id: str, *, kind: str, title: str, url: str | None = None
) -> str:
    params: dict[str, Any] = {"workspace_id": workspace_id, "type": kind}
    if url is not None:
        params["url"] = url
    created = cmux_rpc("surface.create", **params)
    surface = created.get("surface_id") or created.get("id")
    if not surface:
        raise CmuxSlotsError(f"cmux did not return a {kind} surface id for {title}")
    rename_tab(surface, title)
    return surface


def ensure_surface(
    workspace_id: str, *, kind: str, title: str, url: str | None = None
) -> tuple[str, bool]:
    existing = find_surface(workspace_id, title)
    if existing:
        return existing, False
    return create_surface(workspace_id, kind=kind, title=title, url=url), True


def list_workspaces() -> list[dict[str, Any]]:
    proc = run([str(CMUX), "--json", "workspace", "list"], check=False)
    if proc.returncode != 0:
        return []
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("workspaces", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def workspace_id_from_item(item: dict[str, Any]) -> str | None:
    for key in ("id", "workspace_id", "workspaceId", "uuid", "ref", "handle"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def item_matches_slot(item: dict[str, Any], slot: int) -> bool:
    text = json.dumps(item, sort_keys=True)
    return marker(slot) in text or default_title(slot) in text


def workspace_exists(workspace_id: str) -> bool:
    return (
        run([str(CMUX), "workspace", "select", workspace_id], check=False).returncode
        == 0
    )


def find_workspace(slot: int, state: dict[str, Any]) -> str | None:
    stored = state.get("slots", {}).get(str(slot), {}).get("workspace_id")
    if isinstance(stored, str) and stored and workspace_exists(stored):
        return stored
    for item in list_workspaces():
        if item_matches_slot(item, slot):
            found = workspace_id_from_item(item)
            if found:
                return found
    return None


def first_surface(workspace_id: str) -> str:
    surfaces = list_surfaces(workspace_id)
    if not surfaces:
        raise CmuxSlotsError(f"workspace {workspace_id} has no initial surface")
    found = surface_id(surfaces[0])
    if not found:
        raise CmuxSlotsError(f"workspace {workspace_id} surface list has no id")
    return found


def create_workspace(slot: int) -> str:
    path = slot_path(slot)
    workspace = cmux_rpc("workspace.create", cwd=str(path))
    workspace_id = workspace.get("workspace_id") or workspace.get("id")
    if not workspace_id:
        raise CmuxSlotsError(f"cmux did not return a workspace id for slot {slot}")

    cmux_rpc("workspace.rename", workspace_id=workspace_id, title=default_title(slot))
    describe_workspace(workspace_id, slot)
    pin_workspace(workspace_id)

    agent_surface = first_surface(workspace_id)
    rename_tab(agent_surface, "agent")
    send_command(agent_surface, coding_agent_command(slot))

    return workspace_id


def close_workspace(workspace_id: str) -> None:
    run([str(CMUX), "workspace", "close", workspace_id], check=False)


def validate_slot(slot: int) -> None:
    path = slot_path(slot)
    if not path.is_dir():
        raise CmuxSlotsError(f"missing slot directory: {path}")
    if not (path / ".git").exists():
        raise CmuxSlotsError(f"slot is not a git worktree: {path}")
    if not (path / ".env").is_file():
        raise CmuxSlotsError(f"slot is missing .env: {path}")


def setup_slot(slot: int, *, recreate: bool, state: dict[str, Any]) -> str:
    validate_slot(slot)
    existing = find_workspace(slot, state)
    if existing and recreate:
        close_workspace(existing)
        existing = None
    if existing:
        pin_workspace(existing)
        describe_workspace(existing, slot)
        return existing
    return create_workspace(slot)


def start_slot_app(
    slot: int, *, state: dict[str, Any], force: bool = False
) -> tuple[str, str]:
    workspace_id = setup_slot(slot, recreate=False, state=state)
    state.setdefault("slots", {})[str(slot)] = {
        "workspace_id": workspace_id,
        "title": default_title(slot),
        "path": str(slot_path(slot)),
        "frontend_url": frontend_url(slot),
    }
    dev_surface, _created = ensure_surface(
        workspace_id, kind="terminal", title="dev log"
    )
    ensure_surface(
        workspace_id,
        kind="browser",
        title="browser",
        url=frontend_url(slot),
    )
    status = app_status(slot)
    if force or status == "down":
        send_command(dev_surface, dev_command(slot))
        return workspace_id, "sent make dev"
    if status == "up":
        return workspace_id, "already up"
    return workspace_id, "partial; not started without --force"


def parse_slots(values: list[str]) -> list[int]:
    if not values or values == ["all"]:
        return list(range(1, SLOT_COUNT + 1))
    slots: list[int] = []
    for value in values:
        slot = int(value)
        if slot < 1 or slot > SLOT_COUNT:
            raise argparse.ArgumentTypeError(f"slot must be 1-{SLOT_COUNT}: {slot}")
        slots.append(slot)
    return sorted(set(slots))


def parse_slot(value: str) -> int:
    slot = int(value)
    if slot < 1 or slot > SLOT_COUNT:
        raise argparse.ArgumentTypeError(f"slot must be 1-{SLOT_COUNT}: {slot}")
    return slot


def cmd_up(args: argparse.Namespace) -> int:
    ensure_cmux(restart=args.restart_cmux)
    state = state_load()
    state.setdefault("slots", {})
    for slot in parse_slots(args.slots):
        workspace_id = setup_slot(slot, recreate=args.recreate, state=state)
        state["slots"][str(slot)] = {
            "workspace_id": workspace_id,
            "title": default_title(slot),
            "path": str(slot_path(slot)),
            "frontend_url": frontend_url(slot),
        }
        print(f"slot {slot}: {workspace_id} {slot_path(slot)}")
    state_save(state)
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    state = state_load()
    for slot in range(1, SLOT_COUNT + 1):
        stored = state.get("slots", {}).get(str(slot), {}).get("workspace_id", "-")
        status = (
            "ready"
            if slot_path(slot).is_dir() and (slot_path(slot) / ".env").is_file()
            else "missing"
        )
        print(
            f"slot {slot}: {status} workspace={stored} "
            f"app={app_status(slot)} backend=:{backend_port(slot)} "
            f"frontend=:{frontend_port(slot)} path={slot_path(slot)}"
        )
    return 0


def cmd_dev(args: argparse.Namespace) -> int:
    ensure_cmux(restart=args.restart_cmux)
    state = state_load()
    workspace_id, action = start_slot_app(args.slot, state=state, force=args.force)
    state_save(state)
    print(
        f"slot {args.slot}: workspace={workspace_id} app={app_status(args.slot)} "
        f"action={action} backend={backend_url(args.slot)} frontend={frontend_url(args.slot)}"
    )
    return 0


def cmd_title(args: argparse.Namespace) -> int:
    ensure_cmux(restart=args.restart_cmux)
    state = state_load()
    workspace_id = setup_slot(args.slot, recreate=False, state=state)
    title = task_title(args.slot, args.title)
    cmux_rpc("workspace.rename", workspace_id=workspace_id, title=title)
    state.setdefault("slots", {})[str(args.slot)] = {
        "workspace_id": workspace_id,
        "title": title,
        "path": str(slot_path(args.slot)),
        "frontend_url": frontend_url(args.slot),
    }
    state_save(state)
    print(f"slot {args.slot}: title={title}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    ok = True
    print(f"cmux binary: {CMUX} {'ok' if CMUX.exists() else 'missing'}")
    print(
        f"coding agent: {os.environ.get('CODING_AGENT_CMD') or shutil.which('claude') or Path.home() / '.local' / 'bin' / 'claude'}"
    )
    for slot in parse_slots(args.slots):
        try:
            validate_slot(slot)
            print(f"slot {slot}: ok app={app_status(slot)}")
        except CmuxSlotsError as exc:
            ok = False
            print(f"slot {slot}: {exc}")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage cmux workspaces for fixed Life Assistant slots."
    )
    sub = parser.add_subparsers(dest="command")

    up = sub.add_parser("up", help="Create/reuse lightweight coding-agent workspaces")
    up.add_argument("slots", nargs="*", help="Slot numbers, or 'all' (default)")
    up.add_argument(
        "--recreate", action="store_true", help="Close and rebuild matching workspaces"
    )
    up.add_argument(
        "--restart-cmux",
        action="store_true",
        help="Quit/reopen cmux if its socket is stuck",
    )
    up.set_defaults(func=cmd_up)

    list_cmd = sub.add_parser("list", help="Show local slot/workspace mapping")
    list_cmd.set_defaults(func=cmd_list)

    dev = sub.add_parser(
        "dev", help="Create/reuse a slot log/browser surface and start the app"
    )
    dev.add_argument("slot", type=parse_slot, help=f"Slot number 1-{SLOT_COUNT}")
    dev.add_argument(
        "--force", action="store_true", help="Send make dev even if ports are active"
    )
    dev.add_argument(
        "--restart-cmux",
        action="store_true",
        help="Quit/reopen cmux if its socket is stuck",
    )
    dev.set_defaults(func=cmd_dev)

    title = sub.add_parser("title", help="Set a short cmux workspace task title")
    title.add_argument("slot", type=parse_slot, help=f"Slot number 1-{SLOT_COUNT}")
    title.add_argument("title", help="Short task title")
    title.add_argument(
        "--restart-cmux",
        action="store_true",
        help="Quit/reopen cmux if its socket is stuck",
    )
    title.set_defaults(func=cmd_title)

    doctor = sub.add_parser("doctor", help="Check fixed slot prerequisites")
    doctor.add_argument("slots", nargs="*", help="Slot numbers, or 'all' (default)")
    doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        args = parser.parse_args(["up"])
    try:
        return args.func(args)
    except (CmuxSlotsError, ValueError, subprocess.SubprocessError) as exc:
        print(f"cmux-slots: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
