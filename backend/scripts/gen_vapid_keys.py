"""Generate VAPID keys for Web Push.

Run once per Life Assistant instance:

    uv run python backend/scripts/gen_vapid_keys.py

Writes the EC P-256 private key to `data/vapid_private.pem` and prints
the matching public key (urlsafe-base64 raw uncompressed point) plus
ready-to-paste `.env` lines. Idempotent: refuses to overwrite an existing
private key file unless `--force` is given.
"""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KEY_PATH = REPO_ROOT / "data" / "vapid_private.pem"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_KEY_PATH,
        help="Where to write the PEM (default: data/vapid_private.pem)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing private key file.",
    )
    args = ap.parse_args()

    out_path: Path = args.out
    if out_path.exists() and not args.force:
        print(
            f"refusing to overwrite existing key at {out_path}. Pass --force to regenerate.",
            file=sys.stderr,
        )
        return 2

    out_path.parent.mkdir(parents=True, exist_ok=True)

    priv = ec.generate_private_key(ec.SECP256R1())
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    out_path.write_bytes(pem)
    out_path.chmod(0o600)

    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    pub_b64 = base64.urlsafe_b64encode(pub_raw).rstrip(b"=").decode("ascii")

    rel_path = out_path.relative_to(REPO_ROOT) if out_path.is_absolute() else out_path

    print(f"VAPID private key written to {out_path}")
    print()
    print("Add these to .env:")
    print()
    print(f"VAPID_PRIVATE_KEY_PATH={rel_path}")
    print(f"VAPID_PUBLIC_KEY={pub_b64}")
    print("VAPID_CONTACT_EMAIL=mailto:you@example.com")
    return 0


if __name__ == "__main__":
    sys.exit(main())
