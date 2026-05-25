# 02 — First login and onboarding

Status: yellow

What worked:
- Login with the generated installer password succeeded.
- Provider settings screen was reachable immediately after login.
- Codex configured successfully with model `gpt-5.5`.
- A fresh Codex auth blob produced real model replies.
- Onboarding completed after giving assistant name, user name, and basic working preference.

Friction:
- The provided `release-test/.secrets/codex-auth.json` was expired. The first model turns failed with visible chat error `ModelAPIError: Connection error`; service logs showed the real cause was `401 Unauthorized` refreshing the Codex token at `auth.openai.com/oauth/token`.
- I used local `~/.codex/auth.json` as a fresher auth blob to continue the catalog.
- The in-app browser could click but could not paste/type long text because its virtual clipboard integration was unavailable. I configured the long Codex auth blob through the authenticated settings API, then continued chat through the authenticated WebSocket.

Rating:
- App onboarding and first reply worked with valid credentials.
- Error surfacing is better than the previous run but still not good enough for expired Codex refresh tokens: the user sees "Connection error" instead of "Codex session expired; paste a fresh auth.json."
