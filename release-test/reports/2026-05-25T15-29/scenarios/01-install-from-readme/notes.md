# 01 — Install From README

Status: green

What worked:
- Reset the VPS and installed from the public `rev` branch curl flow.
- Installer passed apt/systemd preflight on Ubuntu 26.04 LTS.
- Installed Node 22, Codex CLI, standalone uv, and uv-managed Python 3.11.15.
- Ran all Alembic migrations, including typed Codex credential storage.
- Issued a real Let's Encrypt certificate for `157-180-120-244.sslip.io`.
- Built the frontend and enabled `life-assistant.service` plus `life-assistant-backup.timer`.

Notes:
- Final install ran at commit `f7f7f6c`.
- The earlier first-install service restart warning is gone.
- Existing frontend build warnings remain non-blocking.

Rating:
- Green.
