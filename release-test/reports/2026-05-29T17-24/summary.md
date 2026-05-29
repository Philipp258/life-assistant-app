# Release retest: self-learning follow-up

Target: `root@167.233.17.131` / `https://167-233-17-131.sslip.io/`

Branch: `codex/extend-release-test-scenarios`

Final deployed commit: `9066de2`

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

## Checks

- `uv run ruff format --check app tests/test_agent_prompt_skills.py tests/test_root_deploy_invariants.py`
- `uv run ruff check app tests/test_agent_prompt_skills.py tests/test_root_deploy_invariants.py`
- `uv run pytest tests/test_agent_prompt_skills.py tests/test_root_deploy_invariants.py`
- `uv run ruff format --check app tests/test_default_routines.py tests/test_agent_prompt_skills.py tests/test_root_deploy_invariants.py`
- `uv run ruff check app tests/test_default_routines.py tests/test_agent_prompt_skills.py tests/test_root_deploy_invariants.py`
- `uv run pytest tests/test_agent_prompt_skills.py tests/test_root_deploy_invariants.py tests/test_default_routines.py`
