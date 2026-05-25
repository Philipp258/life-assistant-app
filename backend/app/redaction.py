"""Scrub bearer tokens out of strings before they hit the logger.

httpx raises `LocalProtocolError("Illegal header value b'Bearer …'")`
when an Authorization header contains forbidden characters (newlines,
control chars). The exception's `str(exc)` carries the full offending
header — and any `log.warning("…: %s", exc)` then dumps the entire
credential into journald. See issue #129.

The validator on incoming API keys already rejects multi-line input,
but defence-in-depth is cheap: redact anything that looks like a
bearer payload on every log line that quotes a provider exception.
"""

from __future__ import annotations

import re

# httpx wraps a malformed Authorization header in a bytes repr — `b'…'` —
# inside the `LocalProtocolError` message. Match that whole repr first
# so a payload containing whitespace (e.g. a Codex JSON blob with
# spaces between fields) is still scrubbed in full.
_BEARER_IN_BYTES_REPR = re.compile(r"b'Bearer\s[^']*'", re.DOTALL)
# Plain `Bearer <token>` — a single opaque token, no internal whitespace.
_BEARER_PLAIN = re.compile(r"Bearer\s+\S+")


def redact_bearer(text: str) -> str:
    """Replace every `Bearer <payload>` sequence with `Bearer ***`."""
    cleaned = _BEARER_IN_BYTES_REPR.sub("b'Bearer ***'", text)
    cleaned = _BEARER_PLAIN.sub("Bearer ***", cleaned)
    return cleaned
