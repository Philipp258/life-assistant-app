# 01 — Install from the README

Status: red
Severity: blocker

What I tried: followed the README intent on a fresh Hetzner Ubuntu 26.04 VPS at `167.233.17.131`. Because this was a branch release test, I used `LIFE_ASSISTANT_REF=codex/extend-release-test-scenarios` as instructed by `RUNNER.md`.

What worked: once I substituted the actual GitHub repo/branch (`Philipp258/life-assistant-app`, commit `f1d3c2b`), the installer completed cleanly. It installed system packages, Node 22, pnpm, Codex CLI, uv/Python 3.11, ran Alembic migrations, built the frontend, issued a real Let's Encrypt cert for `167-233-17-131.sslip.io`, enabled `life-assistant.service`, and enabled `life-assistant-backup.timer`.

What broke: the README command still points at `Philipp258/life-assistant`, and `https://raw.githubusercontent.com/Philipp258/life-assistant/main/deploy/install.sh` returned 404. A real operator using the README literally would fail before the installer starts.

Rating: install implementation looks healthy, but the README repo URL mismatch is a setup blocker.
