# 10 — Self-update

**Status:** green

## Tried

- Asked Ada to update itself to the latest configured version.
- Opened the self-update task.
- Checked the VPS service state afterwards.

## Worked

- Ada created an update task and used the self-update skill.
- The task started `life-assistant-update.service` directly with `systemctl`.
- The update service completed successfully and reported the deployed branch/commit.
- The app stayed reachable, prior data remained present, and `life-assistant.service` was active afterwards.
- `life-assistant-update.service` runs without `User=`/`Group=`.

## Friction

- None that affected the user goal. The update was already current, which is expected for this branch retest.

## Rating

Green. The self-update flow exercised the intended root systemd path.
