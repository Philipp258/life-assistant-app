# 02 — First login and onboarding

**Status:** red
**Severity:** blocker

## What I tried

After the (heavily worked-around) install succeeded, opened
`https://178-104-137-208.sslip.io/`, signed in with the seeded
password, and walked the onboarding screen as a first-time user.

## What worked

- Login screen is minimal and obvious — one password field, one
  button. Sign-in worked first try.
- After login the welcome panel renders. Sections for each provider
  (OpenAI / OpenRouter / Z.ai / ChatGPT subscription via Codex) are
  clearly grouped and the help text on the Codex section tells you to
  paste `~/.codex/auth.json` contents.
- The "Auto" preferred-provider behavior, and the explanation of how
  the order falls through, is well documented inline.

## What broke

### 1. Save buttons in the welcome / provider settings panel do not fire

After pasting the Codex auth.json into its textbox and clicking the
section's enabled "Save" button — and again for the Tools section's
Brave API key — the button visually responded but **no PUT request
was issued**. Server logs only showed the periodic
`GET /api/identity` polling, never any
`PUT /api/settings/providers/codex` or
`PUT /api/settings/runtime/brave_api_key`. After reloading the page,
every provider section still said "Not configured".

Tried: `agent-browser click @ref`, `find role button click --name
"Save"`. Both reported success at the CLI level; neither resulted in a
network request server-side. The textbox values were correctly set
(verified via `get value`), and the Save button toggled from disabled
to enabled when content was present, so the form *thought* it was
ready to submit — it just never submitted.

Worked around by calling the underlying API directly with the session
cookie:

```
PUT /api/settings/providers/codex   { auth_json, chat_model: null }
PUT /api/settings/runtime/brave_api_key   { value: "..." }
PUT /api/settings/providers/preferred-chat   { preferred_chat_provider: "codex" }
```

All three returned 200 and the settings stuck.

A real first-time user cannot get past onboarding if Save does not
fire. **This is the actual scenario-02 blocker.**

Likely cause is something in the shadcn Button + form submit wiring
that doesn't trigger from synthetic CDP-level clicks — possible
candidates: a missing `type="submit"`, an `onClick` that needs
`isTrusted`, or a form-state check that isn't satisfied until after a
React render the click never waits for. Worth reproducing manually
before shipping.

### 2. Codex chat completely non-functional on a `prolite` ChatGPT account

Once provider settings were saved out-of-band, sending the first chat
message produced a server-side error and a generic
"Something went wrong handling that — your message wasn't answered.
Please try again." in the UI.

Server log:

```
pydantic_ai.exceptions.ModelHTTPError: status_code: 400,
  model_name: gpt-5-codex,
  body: {'detail': "The 'gpt-5-codex' model is not supported when
    using Codex with a ChatGPT account."}
```

Tried every plausible model name by setting `codex_chat_model`
explicitly and re-sending: `gpt-5-codex`, `gpt-5.1-codex`, `gpt-5`,
`gpt-5.1`, `gpt-5.1-mini`, `codex`, `o4-mini`, `gpt-4o-mini`. All
returned the same shape — `400 "The '<X>' model is not supported when
using Codex with a ChatGPT account."`

The provided account is `chatgpt_plan_type: "prolite"`. Either:

- The Codex API gates *which* models a `prolite` plan can call, and
  none of the obvious names are in the allowlist (i.e. the README's
  "Supported chat providers → ChatGPT subscription through Codex
  auth" claim does not hold for this plan tier).
- Or the Codex backend gates on an `originator` / client-identity
  header that the real `codex` CLI sends and Life Assistant does not,
  and rejects all model requests from unknown clients.

Either way, the only provider the user supplied for this release test
is unusable end-to-end. **Scenarios 03–07 all depend on a working
chat backend and are blocked.**

### 3. Default Codex model is internally inconsistent

`backend/app/agent/providers/codex.py:42` sets
`DEFAULT_CODEX_MODEL = "gpt-5.1-codex"` but
`backend/app/provider_settings/service.py:61` defaults the *configured*
`codex` chat model to `"gpt-5-codex"`. Both happen to fail on this
account, so it didn't matter today — but a future fix for one
shouldn't be undone by the other. Pick one default and have both
files import it.

## Rate

- **Onboarding flow shape:** good — clear sections, sensible help
  text, doesn't ask for things up front it doesn't need.
- **Save reliability:** broken via standard browser automation;
  unconfirmed whether a real human clicker hits the same bug.
- **Codex-account compatibility:** the documented happy path
  ("ChatGPT subscription through Codex auth") does not produce a
  working chat on at least one real ChatGPT plan. If this is meant to
  be a supported provider, either the model defaults are wrong, the
  auth flow is incomplete, or the README needs a "minimum plan tier"
  caveat.

## Recommendations before shipping

1. Reproduce the Save bug manually. If a real-user click also fails,
   fix the form/button wiring before anything else — onboarding does
   not survive it.
2. Verify Codex-via-ChatGPT-subscription end-to-end on each plan tier
   you claim to support (Plus / Pro / Team / Enterprise / Prolite).
   Update the README with the tested set.
3. Surface the Codex 400 model-not-supported response in the UI as
   "Codex rejected this model for your account; try another" instead
   of the opaque "Something went wrong" toast.
4. Align `DEFAULT_CODEX_MODEL` and the service-layer codex default.
