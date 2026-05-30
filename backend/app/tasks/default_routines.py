"""Default assistant routines, seeded at boot.

`ensure_default_routines` runs from the FastAPI lifespan (next to
`ensure_user` / `get_or_create_main_session`) and materializes the
recurring assistant tasks defined in this module.

Idempotent by stable default key: once a routine key is materialized,
`seeded_defaults` records it permanently. Title and brief become
user-owned after creation; boot seeding never mutates or resurrects it.

Every routine is seeded with a future `do_at` (not just `due_at`):
`runner.should_start_task` treats `do_at IS NULL` as eligible-now,
which would wake the routine immediately at first boot.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.defaults.models import SeededDefault
from app.datetime_utils import utc_now
from app.tasks.models import IntervalUnit, Task
from app.tasks.schemas import TaskCreate
from app.tasks.service import create_task

CONSOLIDATION_TITLE = "Daily consolidation"
COLLECT_TITLE = "Collect improvement items"
DISK_SPACE_TITLE = "Weekly disk space check"
TASK_LOG_MAINTENANCE_TITLE = "Task log maintenance"


CONSOLIDATION_BRIEF = """\
You wake to harvest durable bits from recent main-chat activity and \
finished tasks into the knowledge store. The main chat is ephemeral for \
you — anything worth keeping has to land in knowledge or it's \
gone from your view.

## What to look at

Window starts at the previous completion timestamp in the Run context \
block; on the first cycle, look back one cadence. Find main-chat \
messages and tasks completed in that window. 
Create knowledge for things that seem worth preserving.
"""


COLLECT_BRIEF = """\
You wake to scan recent activity for concrete moments that should have \
been captured as improvement items but weren't. Improvement items are \
evidence — discrete moments where the assistant did something wrong, \
inefficient, confusing, or otherwise worth learning from.

## Scope

Window starts at the previous completion timestamp in the Run context \
block; on the first cycle, look back one cadence. Review main-chat and \
task activity in that window.

## What counts

Look for missed learning opportunities: a wrong assumption, tool fumble, \
badly landed answer, inefficient detour, or missed context the user had \
already shared. Skip routine work and anything already captured; check \
existing improvement items, including resolved ones, before creating new \
ones.

For each genuine opportunity, create an assistant-owned improvement task. \
Its description must stand \
alone: what happened, what was off, and why it matters. Avoid speculative \
or vague "could be nicer" items.

Each item becomes its own task that classifies the evidence and proposes a \
change in the relevant surface (behavior, user fact, skill, or knowledge) \
— or closes silently if it's an app bug, infrastructural, or doesn't \
cleanly fit. Don't pre-classify here; file the moment and let the task \
triage.

Quiet cycle = zero items. Saying nothing is better than padding. \
Call `complete_task` when done; the task auto-respawns for the next cycle.

Tone: terse, observational, evidence-driven. You are only collecting \
evidence; each created improvement task handles classification and any \
proposal."""


DISK_SPACE_BRIEF = """\
Please check disk space usage of the machine you are running on via the bash tool.
Clean up things where you are 100% certain they are fine to clean. Otherwise raise potential issues
in the completion message.
"""


TASK_LOG_MAINTENANCE_BRIEF = """\
You wake to keep the durable routine logs under \
`data/knowledge/Task Log/` from growing unbounded. Each recurring \
assistant routine reads its own log before acting and appends concrete \
experience after a cycle. The point is to preserve enough history for \
future judgment, not to distill the user's taste into brittle rules.

## What to do

List entries under `Task Log/`. For each, read it and estimate size — \
roughly 4 chars per token; ~80k chars is the ~20k-token line where \
compression starts paying off. Skip anything smaller.

## How to compress

Compress history, not judgment:

- Keep full detail for recent entries.
- Replace older entries with narrative summary: what was suggested or \
  done, the important attributes, and the outcome (liked, skipped, \
  negative feedback, no response, unknown).
- Preserve texture and timing. "Three egg dishes in late March, then the \
  user asked for a break" is useful; "avoid eggs" is not.
- Do not convert the log into rules, principles, or preference lists. \
  Rule distillation is lossy and goes stale.
- Use compression to deprecate stale signal. If old evidence is weak, \
  contradicted by newer entries, or probably no longer applies, say that \
  in the narrative or drop it.
- Do not invent outcomes. If the log does not show whether something \
  worked, leave it as unknown/no response.
- Drop true noise: chitchat, restated routine context, duplicated \
  entries, and detail that would not help a future cycle reason from \
  history.

Structure a compressed log so recent entries remain raw and older entries \
become dated narrative history. The result should still read like logged \
experience, not policy.

## Out of scope

Do NOT promote patterns into core memory, behavior, skills, or any other \
global surface. Logs stay scoped to their own routine. Cross-domain \
transfer can be useful, but only as judgment/context for the agent reading \
a relevant log; don't mechanically port patterns from one domain to \
another.

Quiet cycle = no eligible logs = call `complete_task` with a short \
"nothing to compress" handoff. The routine respawns on the next cycle."""


def _next_weekday_at(now: datetime, weekday: int, hour: int, minute: int = 0) -> datetime:
    """Next occurrence of `weekday` (Mon=0) at HH:MM, strictly in the future."""
    days_ahead = (weekday - now.weekday()) % 7
    if days_ahead == 0 and now.time() >= time(hour, minute):
        days_ahead = 7
    return datetime.combine((now + timedelta(days=days_ahead)).date(), time(hour, minute))


def _tomorrow_at(now: datetime, hour: int, minute: int = 0) -> datetime:
    return datetime.combine((now + timedelta(days=1)).date(), time(hour, minute))


DEFAULT_TYPE = "task_routine"


@dataclass(frozen=True)
class RoutineSpec:
    key: str
    title: str
    description: str
    interval_unit: IntervalUnit
    interval_count: int
    # now -> first do_at (future, so the routine doesn't wake at boot).
    schedule: Callable[[datetime], datetime]


# Cadence/time mirrors the old seed migrations where still relevant:
# consolidation 03:00, collect 04:00, disk-space Mon 10:00. All UTC.
DEFAULT_ROUTINES: tuple[RoutineSpec, ...] = (
    RoutineSpec(
        key="daily-consolidation",
        title=CONSOLIDATION_TITLE,
        description=CONSOLIDATION_BRIEF,
        interval_unit="day",
        interval_count=1,
        schedule=lambda now: _tomorrow_at(now, hour=3),
    ),
    RoutineSpec(
        key="collect-improvement-items",
        title=COLLECT_TITLE,
        description=COLLECT_BRIEF,
        interval_unit="day",
        interval_count=1,
        schedule=lambda now: _tomorrow_at(now, hour=4),
    ),
    RoutineSpec(
        key="weekly-disk-space-check",
        title=DISK_SPACE_TITLE,
        description=DISK_SPACE_BRIEF,
        interval_unit="week",
        interval_count=1,
        schedule=lambda now: _next_weekday_at(now, weekday=0, hour=10),
    ),
    RoutineSpec(
        key="task-log-maintenance",
        title=TASK_LOG_MAINTENANCE_TITLE,
        description=TASK_LOG_MAINTENANCE_BRIEF,
        interval_unit="week",
        interval_count=1,
        # Saturday 11:00 UTC — late enough that the weekly reflection
        # (Sun 09:00) has already run the previous week's entry, so the
        # compression pass sees the fresh raw notes alongside the older
        # ones it might roll up.
        schedule=lambda now: _next_weekday_at(now, weekday=5, hour=11),
    ),
)


LEGACY_TITLE_MATCHES: dict[str, tuple[str, ...]] = {
    "daily-consolidation": (CONSOLIDATION_TITLE,),
    # The production routine drifted to "opportunities" before this ledger
    # existed. Treat that as the same shipped default instead of seeding the
    # canonical title beside it.
    "collect-improvement-items": (COLLECT_TITLE, "Collect improvement opportunities"),
    "weekly-disk-space-check": (DISK_SPACE_TITLE,),
    "task-log-maintenance": (TASK_LOG_MAINTENANCE_TITLE, "Compress task logs"),
}


def _default_was_materialized(db: Session, spec: RoutineSpec) -> bool:
    return db.get(SeededDefault, (DEFAULT_TYPE, spec.key)) is not None


def _record_materialized(db: Session, spec: RoutineSpec, task_id: int | None) -> None:
    if _default_was_materialized(db, spec):
        return
    db.add(
        SeededDefault(
            default_type=DEFAULT_TYPE,
            default_key=spec.key,
            target_table="tasks" if task_id is not None else None,
            target_id=task_id,
        )
    )
    db.commit()


def _find_legacy_routine(db: Session, spec: RoutineSpec) -> Task | None:
    titles = LEGACY_TITLE_MATCHES.get(spec.key, (spec.title,))
    return db.scalars(select(Task).where(Task.title.in_(titles)).order_by(Task.id).limit(1)).first()


def ensure_default_routines(db: Session) -> list[str]:
    """Create any default routine whose stable key has never materialized.

    Defaults are immutable after creation: title/brief/schedule changes in code
    are not reconciled onto existing user-owned routines. Deleting a seeded
    routine leaves its ledger row behind, so restart will not resurrect it.

    Returns the titles created this call (empty once everything exists).
    """
    created: list[str] = []
    for spec in DEFAULT_ROUTINES:
        if _default_was_materialized(db, spec):
            continue
        if legacy := _find_legacy_routine(db, spec):
            _record_materialized(db, spec, legacy.id)
            continue
        task = create_task(
            db,
            TaskCreate(
                title=spec.title,
                description=spec.description,
                assignee="assistant",
                do_at=spec.schedule(utc_now()),
                interval_unit=spec.interval_unit,
                interval_count=spec.interval_count,
            ),
        )
        _record_materialized(db, spec, task.id)
        created.append(spec.title)
    return created
