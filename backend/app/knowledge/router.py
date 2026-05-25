"""HTTP API behind the Knowledge screen.

Reads the same `app.knowledge.store` filesystem layer that the agent
tools use, so chat-driven and UI-driven edits stay symmetric. Errors
from the filesystem layer are surfaced as 400s; path-traversal attempts
land here as `KnowledgeError` and never escape `data/knowledge/`.

Two endpoint groups:
  - `/api/knowledge/...` — entries + folders.
  - `/api/core-memory/...` — the two always-loaded core memory files.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.knowledge import core as core_memory
from app.knowledge import store as fs

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class KnowledgeMeta(BaseModel):
    path: str
    title: str
    id: str
    created: str
    updated: str
    read_only: bool = False


class KnowledgeRead(KnowledgeMeta):
    body: str


class FolderRead(BaseModel):
    path: str
    items: list[KnowledgeMeta]
    folders: list[str]


class TreeRead(BaseModel):
    folders: list[FolderRead]


class KnowledgeSearchHit(BaseModel):
    path: str
    title: str
    created: str
    updated: str
    snippet: str | None
    matched_in: list[str]
    score: int


class KnowledgeSearchResponse(BaseModel):
    hits: list[KnowledgeSearchHit]


class SaveKnowledgeBody(BaseModel):
    body: str
    title: str | None = None


class CreateKnowledgeBody(BaseModel):
    path: str
    title: str | None = None
    body: str = ""


class MoveBody(BaseModel):
    src: str
    dst: str


class FolderBody(BaseModel):
    path: str


class CoreMemoryBody(BaseModel):
    body: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _knowledge_meta(item: fs.Knowledge) -> KnowledgeMeta:
    return KnowledgeMeta(
        path=item.path,
        title=item.title,
        id=item.id,
        created=item.created,
        updated=item.updated,
    )


def _knowledge_read(item: fs.Knowledge) -> KnowledgeRead:
    return KnowledgeRead(
        path=item.path,
        title=item.title,
        id=item.id,
        created=item.created,
        updated=item.updated,
        body=item.body,
    )


def _bad(exc: fs.KnowledgeError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Knowledge endpoints
# ---------------------------------------------------------------------------


@router.get("/knowledge/tree")
def get_tree() -> TreeRead:
    index = fs.folder_index()
    folders = [
        FolderRead(
            path=entry.path,
            items=[_knowledge_meta(k) for k in entry.items],
            folders=entry.folders,
        )
        for entry in sorted(index.values(), key=lambda e: e.path)
    ]
    return TreeRead(folders=folders)


@router.get("/knowledge/search")
def search_knowledge(q: str = "") -> KnowledgeSearchResponse:
    hits = [
        KnowledgeSearchHit(
            path=h.path,
            title=h.title,
            created=h.created,
            updated=h.updated,
            snippet=h.snippet,
            matched_in=h.matched_in,
            score=h.score,
        )
        for h in fs.search(q)
    ]
    return KnowledgeSearchResponse(hits=hits)


@router.get("/knowledge")
def get_knowledge(path: str) -> KnowledgeRead:
    try:
        item = fs.read_knowledge(path)
    except fs.KnowledgeError as exc:
        raise _bad(exc) from exc
    return _knowledge_read(item)


@router.put("/knowledge")
def put_knowledge(path: str, body: SaveKnowledgeBody) -> KnowledgeRead:
    try:
        item = fs.save_knowledge(path, body.body, title=body.title)
    except fs.KnowledgeError as exc:
        raise _bad(exc) from exc
    return _knowledge_read(item)


@router.post("/knowledge", status_code=201)
def create_knowledge(body: CreateKnowledgeBody) -> KnowledgeRead:
    try:
        item = fs.save_knowledge(body.path, body.body, title=body.title)
    except fs.KnowledgeError as exc:
        raise _bad(exc) from exc
    return _knowledge_read(item)


@router.delete("/knowledge", status_code=204)
def delete_knowledge_endpoint(path: str) -> None:
    try:
        fs.delete_knowledge(path)
    except fs.KnowledgeError as exc:
        raise _bad(exc) from exc


@router.post("/knowledge/move")
def move_knowledge_endpoint(body: MoveBody) -> KnowledgeRead:
    try:
        item = fs.move_knowledge(body.src, body.dst)
    except fs.KnowledgeError as exc:
        raise _bad(exc) from exc
    return _knowledge_read(item)


@router.post("/knowledge/folder", status_code=201)
def create_folder_endpoint(body: FolderBody) -> dict[str, str]:
    try:
        out = fs.create_folder(body.path)
    except fs.KnowledgeError as exc:
        raise _bad(exc) from exc
    return {"path": out}


@router.post("/knowledge/folder/rename")
def rename_folder_endpoint(body: MoveBody) -> dict[str, str]:
    try:
        out = fs.rename_folder(body.src, body.dst)
    except fs.KnowledgeError as exc:
        raise _bad(exc) from exc
    return {"path": out}


@router.delete("/knowledge/folder", status_code=204)
def delete_folder_endpoint(path: str) -> None:
    try:
        fs.delete_folder(path)
    except fs.KnowledgeError as exc:
        raise _bad(exc) from exc


# ---------------------------------------------------------------------------
# Core memory endpoints
# ---------------------------------------------------------------------------


@router.get("/core-memory/{name}")
def get_core_memory(name: str) -> dict[str, str]:
    if name not in core_memory.CORE_FILES:
        raise HTTPException(status_code=404, detail="unknown core memory file")
    return {"name": name, "body": core_memory.read(name)}


@router.put("/core-memory/{name}")
def put_core_memory(name: str, body: CoreMemoryBody) -> dict[str, str]:
    if name not in core_memory.CORE_FILES:
        raise HTTPException(status_code=404, detail="unknown core memory file")
    core_memory.write(name, body.body)
    return {"name": name, "body": core_memory.read(name)}
