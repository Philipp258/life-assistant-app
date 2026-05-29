# Release test summary — 2026-05-29T00-09

**Run target:** `root@167.233.17.131`, branch `codex/extend-release-test-scenarios`, final tested commit `c5a5e79`.

**Verdict: shippable for this release-test catalog.** The previous blockers were fixed and retested: install URL, root-only self-update, Knowledge `New`, Codex configured Settings wording, and self-learning capture. All scenarios completed.

## Scoreboard

| # | Scenario | Status | Headline |
|---|----------|--------|----------|
| 01 | Install from README | green | Fresh root-only install succeeded from `life-assistant-app` |
| 02 | First login and onboarding | green | Codex import, voice skip, onboarding, and first chat worked |
| 03 | Simple chat | green | Three-turn chat was coherent and context-aware |
| 04 | Schedule a reminder | green | Future reminder task was created for the correct time |
| 05 | Reminder fires | green | Short-delay reminder completed and posted to main chat |
| 06 | Background task | green | Web research task ran, completed, and handed results back |
| 07 | Knowledge add and recall | green | Assistant note, manual folder/note, edit, and fresh-chat recall worked |
| 08 | Task management | green | Manual create/edit/complete/archive flow worked |
| 09 | Skill lifecycle | green | User skill installed, appeared in UI, and worked in fresh chat |
| 10 | Self-update | green | Chat-triggered root systemd update completed and app stayed reachable |
| 11 | Self-learning | green | Natural feedback created an improvement task, proposed memory, applied after approval, and worked in fresh chat |
| 12 | Open exploration | green | Settings, notifications, and service invariants checked |

## Remaining Notes

1. **Onboarding warning copy is too alarming.** The “Stuck — wrong key, agent not responding?” escape hatch appears even during healthy setup.
2. **Fresh chat is not discoverable.** `/new` works when submitted with Enter, but no visible “new chat” action was obvious.
3. **Task edit wording is easy to misread.** The edit modal and task detail both use “Done” in nearby places.
4. **Task details sometimes under-explain handoffs.** Reminder completion was clear in main chat, but task activity mostly showed the terminal tool marker.
5. **Settings shows saved tool secrets in plaintext.** The Brave key input displays the saved value after saving.

## Fixes Made During This Run

- `aab31c7` fixed Codex server-auth import so a currently valid `/root/.codex/auth.json` can be imported without forcing a failing refresh.
- `c5a5e79` tightened the runtime prompt so natural corrective feedback first creates an `improve-life-assistant` task before proposing/saving behavior memory.

## Validation

- `life-assistant.service`: active after install, update, and self-update.
- `life-assistant.service`, `life-assistant-update.service`, and `life-assistant-backup.service`: no `User=`/`Group=`.
- Final deployed commit on VPS: `c5a5e79`.
- Chat provider: Codex / ChatGPT subscription via root server auth.
- Brave Search setting configured and used by background research.

## Regression Check

Compared with `2026-05-28T22-38`, the three blocker classes are resolved: install URL now points at the app repo, manual Knowledge creation no longer depends on `window.prompt()`, and chat self-update can start the update service. The additional Codex Settings wording issue is also fixed. The expanded self-learning scenario initially exposed a prompt gap; that is fixed and retested in this run.
