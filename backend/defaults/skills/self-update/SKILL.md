---
name: self-update
description: Deploy latest main to the VPS by triggering the update systemd oneshot.
---

# Self-update

Life Assistant ships its own updates: a systemd oneshot runs `deploy/update.sh`
(git pull → build → restart) on the VPS.

Run:

```
/usr/bin/systemctl start --no-block life-assistant-update.service
```

If systemd accepts the job, complete this task with a short handoff saying
the update started and the app will restart shortly. The oneshot takes
~30–60s and kills this process partway through the restart, so don't wait on
the service inside this task.

VPS only — `make dev` has no such unit. If the unit isn't installed, surface
the systemctl error to the user instead of retrying.
