"""CLI: set the singleton user's login password.

Usage: `python -m app.users.set_password <password>`
or `make set-password PASSWORD=<password>`.
"""

from __future__ import annotations

import sys

from app.db import SessionLocal
from app.users.service import set_password


def main(password: str) -> None:
    if not password:
        raise SystemExit("password must not be empty")
    with SessionLocal() as db:
        set_password(db, password)
    print("password updated")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(
            "usage: python -m app.users.set_password <password>",
            file=sys.stderr,
        )
        raise SystemExit(2)
    main(sys.argv[1])
