---
name: add-skills
description: Install agent skills from GitHub when the user wants a new capability. Skills live in data/skills/<name>/SKILL.md. Use when the user asks to add, install, or teach a new skill.
---

# Add skills

Install user skills into `data/skills/<name>/`. A skill is a folder with a
`SKILL.md`: YAML frontmatter (`name`, `description`) plus markdown
instructions. New chat sessions see installed skills in the system prompt.

You are installing for the runtime assistant inside Life Assistant. Default
skills (`add-skills`, `github`, `improve-life-assistant`, `self-update`) live
under `backend/defaults/skills/<name>/SKILL.md` and are **read-only** — the
filesystem tools refuse writes there. To customize a default's behavior,
install a new skill under a different name and use that one instead.

## Where to look

In rough order of curation:

1. `https://github.com/VoltAgent/awesome-agent-skills` — 1000+ community
   skills, indexed and categorized.
2. `https://github.com/sickn33/antigravity-awesome-skills` — 1400+, has
   its own installer CLI we don't use, but the SKILL.md files are
   readable.
3. `https://github.com/openclaw/openclaw/tree/main/skills` — MIT;
   well-written examples (`github`, `gemini`, `notion`, `gh-issues`).
4. Anywhere else the user names. Always check the LICENSE before
   copying — MIT and Apache 2.0 are fine; refuse anything that says
   "source-available", "non-commercial", or no license at all.

## Install

Pick a slug for the skill (`^[a-z0-9][a-z0-9-]*$` — the backend rejects
anything else, so catch it early). Defaults (`add-skills`, `github`,
`improve-life-assistant`, `self-update`) are immutable and their slugs are
reserved. Check `data/skills/*/SKILL.md` first to avoid silently overwriting an
existing user skill.

Fetch the upstream `SKILL.md` with `web_fetch`. The frontmatter must
have `name` and `description` — if it doesn't, the skill is
malformed; refuse. Write to `data/skills/<slug>/SKILL.md`, rewriting
the `name` field to match the folder if it differs (the backend
expects them aligned). Pull in supporting files (`scripts/`,
`references/`, `assets/`) only if the SKILL.md body references them. Keep the install minimal — extra files are
extra surface area.

Confirm to the user with the skill's name, description, and a one-line
summary of what it does.
