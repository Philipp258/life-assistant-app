# Onboarding eval

App: `<APP_URL>`. Login password: `<PASSWORD>`.

You are the eval driver, not the assistant being tested. Drive the app with
the `agent-browser` CLI (run via Bash). Do not read source code, spawn
subagents, or fetch over HTTP; this eval is about the browser experience.

**Tool whitelist:** the only tool you can use is `Bash(agent-browser:*)`. Any other Bash command, Read, Write, WebFetch, Glob, Grep, or subagent call will be silently denied. Don't try.

```
agent-browser open <APP_URL>
agent-browser snapshot -i           # list interactive refs (@e1, @e2, ...)
agent-browser fill @e2 "evalpw"     # type into an element
agent-browser click @e3             # click an element
```

Refs go stale after each page change — re-snapshot before the next interaction. For full reference: `agent-browser skills get core --full`.

In the app, play a programmer trying an assistant for the first time.
Improvise the rest — name, what you do, why you want it. Stay terse and in
character.

Job: complete the onboarding the app puts in front of you. Pass = onboarding ends and the normal app surfaces (TabBar appears, nav unlocked). Fail = it doesn't, or the app isn't showing onboarding when you open it.

Report at the end:

- **pass / fail** — one line; if fail, one-line reason
- **1-5 quality** — only if pass
- **notes** — anything worth mentioning: bugs, glitches, awkward moments, things that surprised you. Free form, as long or short as fits.
