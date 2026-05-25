"""CLI: exit successfully when the installer should seed the first password."""

from __future__ import annotations

from app.users.service import has_user


def main() -> None:
    from app.db import SessionLocal

    with SessionLocal() as db:
        raise SystemExit(1 if has_user(db) else 0)


if __name__ == "__main__":
    main()
