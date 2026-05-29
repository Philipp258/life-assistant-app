# Release retest: self-learning follow-up

Target: `root@167.233.17.131` / `https://167-233-17-131.sslip.io/`

Branch: `codex/extend-release-test-scenarios`

Final deployed commit: `3f9e831`

Scope: partial retest of the edited self-improvement scenarios, plus regressions found while redeploying the PR branch.

## Results

- **11 — Explicit self-improvement request: pass.**
  Asked for a quick podcast recommendation, then explicitly asked Ada to treat the correction as an improvement. Ada created task #17 with concrete evidence, proposed a Core memory behavior update, waited for approval, applied it with `save_core_memory`, and completed the task. Core memory showed the new podcast-duration rule, and a fresh chat then asked "How long is the walk?" before naming a podcast.

- **12 — Routine self-improvement capture: pass after prompt fix.**
  On commit `b851189`, natural "next time" feedback still created an improvement task directly from main chat. After tightening the main prompt and redeploying `1c8a31e`, similar natural feedback stayed in the current chat. Running `Collect improvement items` immediately created task #19 with the missed-learning evidence and a proposal waiting for approval.

- **Self-update task completion: pass after skill fix.**
  The first app-triggered self-update succeeded at the systemd level but left task #16 running because the task waited on blocking `systemctl start` during restart. The self-update skill now uses `systemctl start --no-block life-assistant-update.service` and completes once systemd accepts the job. Retests through app tasks #23 and #24 both completed, and the VPS ended active on `9066de2` with the update service inactive.

- **Process improvement context limit: addressed.**
  The collection routine captured the paused `Process improvement items` routine as task #20. The live task updated the routine description with a bounded-context instruction, and the same instruction is now in the seeded default routine so fresh installs do not repeat the broad grep/context-window failure.

- **Self-improvement context/tool guardrails: pass after runner fixes.**
  The PR now paginates high-volume tool results, compacts task chats before oversized provider calls, retries once after provider context-window errors, and removes the fresh-install `Process improvement items` bulk routine. Targeted backend tests cover tool clamps, task-chat compaction, context-window retry, and fresh default routines.

- **Explicit self-improvement approval lifecycle: pass after label and runner fixes.**
  A redeploy at `b7bc275` fixed the missing `improve-life-assistant` default label; task #26 then showed the `Improve the assistant` label and waited on a structured choice instead of writing memory immediately. A follow-up bug left approval replies stuck/re-asking; `9f6ccfd` fixed task-choice continuation. Fresh task #28 waited for approval, wrote Core memory with `save_core_memory` only after selecting "Apply this wording", called `complete_task`, and ended `Done`. A fresh chat then asked "Do you want it creamy or brothy?" before naming a soup.

- **Routine-captured self-improvement: pass on deployed branch.**
  Natural negative snack feedback in main chat did not explicitly mention self-improvement. Running `Collect improvement items` from the task UI completed and created labeled assistant improvement tasks #29 (`Improve handling of late-work snack constraints`) and #30 (`Improve handling when improvement approval does not resume the task`). The run used paginated chat/task reads and completed without a context-limit pause. The reused VPS still has an old copy of the routine description in its DB, which is expected because default routines are user-owned after creation; fresh-install defaults are covered by tests.

- **Runtime improvement task boundary: pass after follow-up.**
  Task #30 exposed that an improvement task could classify an app runner bug correctly but still patch `/opt/life-assistant` from inside the running app. Commit `3f9e831` keeps the useful runner regression it found and tightens the skill so app-code findings complete with rationale instead of editing repo files. After redeploy, task #32 read the skill, classified the evidence as an app-prompt/default-skill process issue, called `complete_task`, used no edit or shell tools, and left the server checkout clean apart from the expected untracked `data` path.

## Checks

- `uv run ruff format --check app tests/test_agent_prompt_skills.py tests/test_root_deploy_invariants.py`
- `uv run ruff check app tests/test_agent_prompt_skills.py tests/test_root_deploy_invariants.py`
- `uv run pytest tests/test_agent_prompt_skills.py tests/test_root_deploy_invariants.py`
- `uv run ruff format --check app tests/test_default_routines.py tests/test_agent_prompt_skills.py tests/test_root_deploy_invariants.py`
- `uv run ruff check app tests/test_default_routines.py tests/test_agent_prompt_skills.py tests/test_root_deploy_invariants.py`
- `uv run pytest tests/test_agent_prompt_skills.py tests/test_root_deploy_invariants.py tests/test_default_routines.py`
- `uv run ruff check app tests/test_default_labels.py tests/test_boot_seeding.py tests/test_improve_life_assistant_skill.py tests/test_agent_prompt_skills.py tests/test_chat_tools.py tests/test_events.py tests/test_runner.py tests/test_default_routines.py`
- `uv run ruff format --check app tests/test_default_labels.py tests/test_boot_seeding.py tests/test_improve_life_assistant_skill.py tests/test_agent_prompt_skills.py tests/test_chat_tools.py tests/test_events.py tests/test_runner.py tests/test_default_routines.py`
- `uv run pytest tests/test_default_labels.py tests/test_boot_seeding.py tests/test_improve_life_assistant_skill.py tests/test_agent_prompt_skills.py tests/test_chat_tools.py tests/test_events.py tests/test_runner.py::test_user_reply_after_ask_user_choice_runs_followup_turn tests/test_runner.py::test_ask_user_choice_ends_wake_before_empty_output_validation_retry tests/test_runner.py::test_terminal_tool_error_does_not_stop_user_assigned_task_turn tests/test_tasks_tools.py::test_complete_task_records_hidden_handoff tests/test_tasks_tools.py::test_do_create_task_rejects_unknown_labels tests/test_default_routines.py`
- `uv run ruff check app/chat/runner/inputs.py app/chat/runner/turn.py tests/test_runner.py tests/test_improve_life_assistant_skill.py`
- `uv run ruff format --check app/chat/runner/inputs.py app/chat/runner/turn.py tests/test_runner.py tests/test_improve_life_assistant_skill.py`
- `uv run pytest tests/test_runner.py tests/test_improve_life_assistant_skill.py`
- `git diff --check`
