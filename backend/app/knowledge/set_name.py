"""CLI: set the assistant's name or the user's name in app_settings.

Usage:
    python -m app.knowledge.set_name --assistant <name>
    python -m app.knowledge.set_name --user <name>
    python -m app.knowledge.set_name --assistant <name> --user <name>

Mirrors the `make set-password` operator command for the identity fields
introduced when the assistant name moved out of behavior.md.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.knowledge.set_name")
    parser.add_argument("--assistant", help="store as assistant_name in app_settings")
    parser.add_argument("--user", help="store as user_name in app_settings")
    args = parser.parse_args(argv)

    if not args.assistant and not args.user:
        parser.error("provide --assistant and/or --user")

    from app.db import SessionLocal
    from app.knowledge import identity

    with SessionLocal() as db:
        if args.assistant is not None:
            stored = identity.set_assistant_name(db, args.assistant)
            print(f"assistant_name set to {stored!r}")
        if args.user is not None:
            stored = identity.set_user_name(db, args.user)
            print(f"user_name set to {stored!r}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
