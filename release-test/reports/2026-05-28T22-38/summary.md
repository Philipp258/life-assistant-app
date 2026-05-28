# Release test summary — 2026-05-28T22-38

**Run target:** Hetzner `167.233.17.131`, Ubuntu 26.04 LTS, branch `codex/extend-release-test-scenarios`, tested commit `f1d3c2b`.

**Verdict: not shippable as-is.** Most app flows worked once installed and configured, including Codex chat, reminders, background tasks, task management, knowledge recall, and skill install/use. Three release blockers remain: the README install URL points at the wrong repo, manual Knowledge `New` fails in the test browser because it uses `window.prompt()`, and chat-triggered self-update cannot start the systemd update service from the assistant runtime.

## Scoreboard

| # | Scenario | Status | Severity | Headline |
|---|----------|--------|----------|----------|
| 01 | Install from README | red | blocker | README hardcodes `Philipp258/life-assistant`, whose raw install URL returns 404; install passed only after substituting `life-assistant-app` |
| 02 | First login and onboarding | yellow | friction | Login, Codex import, voice skip, and onboarding completed; alarming "Stuck — wrong key" banner appeared during healthy setup |
| 03 | Simple chat | green |  | Three-turn chat was coherent and context-aware |
| 04 | Schedule a reminder | yellow | friction | Stored reminder time was correct, but task cards displayed it two hours late |
| 05 | Reminder fires | green |  | Short-delay reminder fired into main chat and moved to Done archive |
| 06 | Background task | green |  | Espresso-machine research ran in a task, showed tool activity, completed, and handed results back to chat |
| 07 | Knowledge add and recall | red | blocker | Assistant-saved/edit/recall worked, but manual Knowledge `New` failed because `prompt()` is unsupported |
| 08 | Task management | green |  | Manual create/edit/search/complete/archive flow worked |
| 09 | Skill lifecycle | yellow | friction | Skill installed, appeared in UI, and worked in fresh chat; trivial skill response created a task first |
| 10 | Self-update | red | blocker | Assistant could not start `life-assistant-update.service` because `sudo` is blocked by `no_new_privileges` |
| 11 | Open exploration | yellow | friction | Confirmed persistence and settings; main findings match the above blockers/friction |

## Top Friction Points

1. **README install command points at the wrong repository.** The raw URL for `Philipp258/life-assistant/main/deploy/install.sh` returned 404. The branch installed only after using `Philipp258/life-assistant-app`.
2. **Self-update from chat is blocked by service hardening.** The assistant runtime cannot use `sudo` because `no_new_privileges` is set, and direct `systemctl` needs interactive auth.
3. **Manual Knowledge creation depends on `window.prompt()`.** The release-test browser does not support prompt dialogs, so `New` silently fails from the user's perspective and logs a console error.
4. **Reminder UI displays scheduled times two hours late.** Stored `do_at` and assistant text were correct for 09:00, but task cards showed 11:00.
5. **Onboarding shows a scary stuck/wrong-key banner while working.** It did not block setup, but it makes first-use feel unreliable.

## Validation Notes

- Final deployed commit: `f1d3c2b`.
- Runtime branch: `codex/extend-release-test-scenarios`.
- Runtime chat provider: Codex / ChatGPT subscription.
- Codex login status: logged in using ChatGPT.
- Codex plan metadata shown in UI: `prolite`.
- `life-assistant.service`: active/enabled.
- `life-assistant-backup.timer`: active/enabled.
- `life-assistant-update.service`: inactive; no journal entries because it never started.
- Final journal scan found no tracebacks or model errors.

## Regression Check

Compared with `2026-05-25T15-29`, this run newly exercises reminder firing, direct task management, skill lifecycle, self-update, and open exploration. The core chat/task/knowledge happy paths remain mostly healthy. The new catalog exposed two important blockers that the old catalog did not cover: manual Knowledge `New` and self-update.
