"""Skills: filesystem-backed AgentSkills folders the agent can install + use.

Defaults ship with the app under `backend/defaults/skills/<name>/SKILL.md`
(tracked in git, immutable at runtime). User-installed skills live under
`data/skills/<name>/SKILL.md` (gitignored, fully editable).

At prompt-assembly time the agent gets a compact `<skills>` footer
(~100 tokens per skill); the full body is read on demand via the existing
`read_file` tool. The filesystem is the sole source of truth — there's
no DB table.
"""

from app.skills.store import (
    Skill,
    SkillError,
    SkillMeta,
    SkillSource,
    list_skills,
    read_skill,
    render_skills_for_prompt,
)

__all__ = [
    "Skill",
    "SkillError",
    "SkillMeta",
    "SkillSource",
    "list_skills",
    "read_skill",
    "render_skills_for_prompt",
]
