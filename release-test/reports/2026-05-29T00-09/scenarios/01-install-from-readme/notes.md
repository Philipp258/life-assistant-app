# 01 — Install from README

**Status:** green

## Tried

- Reset `root@167.233.17.131`: stopped/removed existing units, deleted `/opt/life-assistant`, `/var/lib/life-assistant`, `/etc/life-assistant`, removed the old `life-assistant` Unix user, and removed stale sudoers/unit files.
- Installed from the PR branch using the README/deploy URL shape for `Philipp258/life-assistant-app`.
- Seeded `/root/.codex/auth.json` and root-owned app paths.
- Verified `life-assistant.service`, `life-assistant-update.service`, and `life-assistant-backup.service` omit `User=` and `Group=`.

## Worked

- Fresh install completed and served the app at the generated `sslip.io` HTTPS URL.
- The installed checkout was on the release-test branch.
- Service ran as root with root-owned app paths.
- The old Unix user did not exist after reset.

## Friction

- Vite still reports the existing CSS minification warning and chunk-size warning during production build. They did not block deploy.

## Rating

Green. The corrected repository URL and root-only deployment model worked on a clean VPS.
