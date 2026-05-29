---
name: improve-life-assistant
description: Inside an improve-life-assistant task — classify the evidence, propose a confirmed durable change in the right surface, and apply it after approval. Not for main chat.
---

# Improve the Assistant

You are inside one improvement task. The description is evidence — what
happened and what was off. Turn it into the smallest durable change that
improves future behavior. Propose first; write only after approval.

## Classify first

Decide which surface the evidence actually points at:

- **behavior** — the assistant's tone, style, length, format, when to ask
  vs act, choice patterns.
- **user-fact** — a durable fact about the user (role, projects,
  environment, schedule, relationships).
- **skill** — a procedure the assistant follows: new, edit, scope, or
  remove. If the relevant skill lives under `backend/defaults/skills/`,
  reclassify as `app-prompt` — defaults are read-only and only change by
  deploy.
- **knowledge** — domain context the assistant should know: new, edit,
  scope, or remove.
- **app-bug** — the app itself misbehaved: crash, broken flow, truncated
  stream, missing feature, infrastructural glitch. Not something a
  runtime memory change fixes.
- **app-prompt** — the cause traces to a baked-in system prompt or default
  skill that you can't edit at runtime.
- **skip** — ambiguous evidence, one-off noise, or something already
  contradicted by recent history.

Genuinely consider the app classes before defaulting to a learnable surface.
A lot of "the assistant did X wrong" moments are actually app bugs or
wired-in prompt behavior, not memory gaps. Forcing those into behavior or
knowledge ships brittle rules that paper over the real cause.

Runtime improvement tasks do not patch the app checkout. If evidence points
at `app-bug` or `app-prompt`, do not edit repo files or use shell commands
to change code; call `complete_task` with a short rationale so coding and
deploy changes can happen outside the app. `skip` also closes the task with a
short rationale and stops. No proposal, no user-facing surface. The rationale
is useful future signal, so name what you suspected and why.

## Action for behavior / user-fact / skill / knowledge

If the latest user message answers a previous `ask_user_choice`, handle
that answer before proposing anything new:

- Apply / yes / chosen alternative: make exactly the approved write, then
  call `complete_task`.
- Revise / custom wording: draft the revised exact change and ask again.
- Skip / no: call `complete_task` with a short note that no change was made.

Never ask the same approval question twice.

Read the current state of the surface you picked. The goal is not to
produce a memory edit; the goal is to reduce the chance that this failure
happens again.

Use the abstraction ladder:

raw case -> narrow rule -> broader principle -> intent / role

Pick the level that would have prevented the miss without overfitting one
incident. Avoid raw-case rules unless the user clearly wanted a specific
rule. Avoid broad personality changes unless several cases support them.

## User-facing review

The visible moment should feel like a normal conversation about what the
assistant should learn. Use conversational, easy language.

Choose the next move with judgment. Sometimes the right answer is to close
the task with a short rationale because no durable change follows. Sometimes
the right answer is one focused question because the evidence is promising
but underspecified. Sometimes the right answer is a concrete proposal the
user can approve, revise, or skip.

If you propose a durable write, show the exact wording that would be saved,
not a paraphrase. Keep the `ask_user_choice` question and options short and
clear. Then call `ask_user_choice` and stop.

Do not call `save_core_memory`, `save_knowledge`, `write_file`, or
`edit_file` in the same run that asks. Only after the user later chooses a
concrete option should you make the approved write. Drop on no, revise on
edit.

When editing a skill or knowledge note, write for the runtime assistant who
will read it later — "you" means that assistant inside the app, not the
human reviewing the change.

Don't spawn sibling tasks; this one task handles this evidence.
