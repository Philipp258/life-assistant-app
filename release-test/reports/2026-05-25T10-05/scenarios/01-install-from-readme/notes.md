# 01 — Install from the README

Status: yellow

Target was Hetzner `178.105.219.48`, Ubuntu 26.04 LTS, branch `rev`.

What worked:
- The final installer on `rev` accepts Ubuntu 26.04 via the new apt + systemd preflight.
- It installed Node 22, standalone uv, uv-managed Python 3.11.15, backend deps, frontend deps, migrations, systemd units, backup timer, sudoers, and a real Let's Encrypt cert for `178-105-219-48.sslip.io`.
- The app came up healthy at `https://178-105-219-48.sslip.io/`; `systemctl is-active life-assistant` returned `active`, and `/api/health` returned `{"status":"ok","env":"prod"}`.
- A final rerun using the branch raw URL was idempotent and completed without printing a second password.

Friction / deviations:
- The first install attempt found a real blocker in the committed installer: uv was invoked as `life-assistant` while cwd/process metadata still pointed at `/root`, producing `failed to open file /root/uv.toml: Permission denied`.
- I fixed and pushed `d121593` during the run. Immediately after that push, the VPS's GitHub raw edge still served the prior branch script, so I used the commit raw URL for the successful install. Later the branch raw URL caught up and an idempotent branch-url rerun passed.
- Because of the mid-run fix and manual probe, this was not a perfectly clean one-shot final-commit install from a blank VPS, although all final installer steps were exercised successfully.

Rating:
- Yellow rather than green only because the run included a mid-test installer fix and a temporary commit-URL workaround for GitHub raw cache. The final branch state looks shippable for this scenario, but a fresh one-shot rerun on a new VPS would be the clean confirmation.
