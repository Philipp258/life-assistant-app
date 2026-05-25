"""Read-only HTTP surface for skills.

Knowledge UI consumes these to render the "Skills (read-only)" card.
Mutation happens only through the agent's filesystem tools — there is
no PUT/POST/DELETE here by design. Default skills (under
`backend/defaults/skills/`) are also rejected by the filesystem tools.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.skills import store

router = APIRouter()


class SkillMetaRead(BaseModel):
    name: str
    description: str
    path: str
    source: store.SkillSource


class SkillRead(SkillMetaRead):
    body: str


class SkillsList(BaseModel):
    skills: list[SkillMetaRead]


@router.get("/skills")
def get_skills() -> SkillsList:
    metas = store.list_skills()
    return SkillsList(
        skills=[
            SkillMetaRead(
                name=m.name,
                description=m.description,
                path=m.path,
                source=m.source,
            )
            for m in metas
        ]
    )


@router.get("/skills/{name}")
def get_skill(name: str) -> SkillRead:
    try:
        skill = store.read_skill(name)
    except store.SkillError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg) from exc
        raise HTTPException(status_code=400, detail=msg) from exc
    return SkillRead(
        name=skill.name,
        description=skill.description,
        path=skill.path,
        body=skill.body,
        source=skill.source,
    )
