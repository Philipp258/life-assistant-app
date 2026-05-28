# 10 — Self-update

**Goal.** Ask the assistant to update the running app through its
self-update flow.

**Persona.** The single operator of this VPS, using chat rather than
SSH to deploy the latest configured ref.

**Done when.** The assistant has attempted the self-update through the
app's intended path, the update task or service has clearly completed
or failed, and the app is reachable afterwards with prior data still
present. If the installed ref is already current, an "already up to
date" result still counts as exercising the flow.

**Rate.** Use judgment. Note whether the assistant chose the right
kind of task, whether progress and failure details were visible,
whether restart/reconnect behavior was understandable, and whether a
non-technical operator would trust the result.
