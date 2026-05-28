---
name: self-update
description: Deploy latest main to the VPS by triggering the update systemd oneshot.
---

# Self-update

Life Assistant ships its own updates: a systemd oneshot runs `deploy/update.sh`
(git pull → build → restart) on the VPS.

Run:

```
/usr/bin/systemctl start life-assistant-update.service
```

The command returns immediately; the oneshot takes ~30–60s and kills this
process partway through the restart. In-flight assistant tasks resume on the
next boot via the watchdog.

VPS only — `make dev` has no such unit. If the unit isn't installed, surface
the systemctl error to the user instead of retrying.
