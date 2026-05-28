# 10 — Self-update

Status: red
Severity: blocker

What I tried: asked the assistant to deploy latest using the self-update flow.

What worked: the assistant created `Deploy latest via self-update`, read the `self-update` skill, and the task details clearly explain what it tried.

What broke: the task could not start `life-assistant-update.service`. `sudo systemctl start life-assistant-update.service` failed because the assistant runtime has `no_new_privileges` set, and direct `systemctl start` required interactive authentication. The task reassigned back to the user with a manual command to run over SSH. `life-assistant-update.service` had no journal entries because it never started.

Rating: self-update from chat is blocked. The failure is well explained, but the intended app path does not work.
