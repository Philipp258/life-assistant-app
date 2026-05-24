# Release test summary — 2026-05-24T00-00

**Run target:** Hetzner CX22, IP `178.104.137.208`, image **Ubuntu
26.04** (not the supported 24.04), branch `rev` (`de12ae8`).

**Verdict: the release is not shippable as-is.** The advertised
end-to-end happy path — "install from README, sign in, configure
ChatGPT-via-Codex auth, start chatting" — fails at every stage
beyond the install transcript, in ways a real first-time user could
not work around.

## Scoreboard

| #  | Scenario                          | Status | Severity | Headline                                                              |
|----|-----------------------------------|--------|----------|-----------------------------------------------------------------------|
| 01 | Install from README               | red    | blocker  | 4 independent install-time bugs; only worked after heavy sed-patching |
| 02 | First login and onboarding        | red    | blocker  | Save button never fires PUT; Codex/ChatGPT account rejects every model |
| 03 | Simple chat                       | red    | blocker  | Blocked by 02 — no model reply, generic toast hides real error        |
| 04 | Schedule a reminder               | red    | blocker  | Blocked by 02                                                          |
| 05 | Background task                   | red    | blocker  | Blocked by 02                                                          |
| 06 | Knowledge add and recall          | red    | blocker  | Blocked by 02                                                          |
| 07 | Read a local file                 | red    | blocker  | Blocked by 02                                                          |

## Top friction points (ranked)

1. **Codex via ChatGPT-subscription auth is broken end-to-end on a
   `prolite` plan.** Every model name tried (`gpt-5-codex`,
   `gpt-5.1-codex`, `gpt-5.1`, `gpt-5.1-mini`, `gpt-5`, `codex`,
   `o4-mini`, `gpt-4o-mini`) returns
   `400 "The '<X>' model is not supported when using Codex with a
   ChatGPT account."` This is the headline issue: the only provider
   the operator handed me does not work, and the README claims it as
   supported. (See scenario 02.)
2. **Provider-settings Save buttons don't fire on click.** Onboarding
   form Save buttons visually respond but never issue the
   corresponding PUT. Real users probably can't configure providers
   at all through the UI. Worked around in this run by calling the
   API directly. (See scenario 02.)
3. **`install.sh` only works on a perfectly-conforming Ubuntu 24.04
   box with sslip.io quota available and Node 20 still compatible
   with the frontend lockfile.** All three of those conditions failed
   here, in three different ways, in sequence. (See scenario 01.)
4. **Repository was private when the README told the operator to
   `curl raw.githubusercontent.com`.** Fixed mid-run. The README
   should not point a stranger at a private URL, and the installer
   should fail with a recognisable message when that happens.
5. **Default Codex model is set in two places** (`agent/providers/codex.py`
   says `gpt-5.1-codex`; `provider_settings/service.py` says
   `gpt-5-codex`). Pick one.

## Sub-blocker findings worth recording

- Generic "Something went wrong" toast in chat hides the actual
  upstream model error. Surfacing the 400 body would have made
  scenarios 02/03 self-diagnosing.
- `update.sh` previously hard-pinned `origin/main`; this run was on
  `rev` thanks to the `LIFE_ASSISTANT_REF` work added in this branch.
  Keep that change.

## What this run says about the release-test catalog itself

- The catalog held up: scenario 01 caught real install-path bugs;
  scenario 02 caught two distinct critical bugs; the
  blocked-by-cascade behavior in RUNNER.md kept the report honest
  about what was and wasn't observed. Good shape.
- The catalog cannot verify anything past the first model reply
  without a working provider. Worth either (a) adding a second
  fallback provider configured before scenario 03 runs, or (b)
  documenting in RUNNER.md that the release-test operator should hand
  in keys for at least one *known-working* provider so chat
  scenarios are not at the mercy of one provider's account quirks.

## Regressions vs. prior run

No prior reports in `release-test/reports/` — this is the first
release test, so the report is the baseline.
