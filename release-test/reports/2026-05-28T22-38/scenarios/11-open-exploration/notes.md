# 11 — Open exploration

Status: yellow
Severity: friction

What I checked: self-update task details, Agent settings, runtime tools settings, Notifications, and persistence of the installed skill/edited knowledge.

Findings: the self-update task detail is useful and transparent: it shows `read_file`, attempted `bash`, the `no_new_privileges` explanation, and `reassign_task`. Agent settings show Codex configured and the server auth file ready to import. Brave API key is blank on this run, but the background task still completed by using available web tooling. Notifications show permission `denied` and subscribed `no` in the test browser; I did not try to enable it because notifications were intentionally out of scope.

Persistence checks: the deployed repo stayed on `f1d3c2b` / `codex/extend-release-test-scenarios`, `release-test-motto` remained installed, and the knowledge note still contained `Steel Finch`.

Rating: exploration completed. Main notable issues were already captured: README URL mismatch, prompt-based Knowledge New, reminder time display, and self-update privilege failure.
