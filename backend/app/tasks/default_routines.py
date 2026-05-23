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
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.defaults.models import SeededDefault
from app.datetime_utils import utc_now
from app.labels.models import Label
from app.tasks.models import IntervalUnit, Task
from app.tasks.schemas import TaskCreate
from app.tasks.service import create_task

REFLECTION_TITLE = "Weekly reflection"
CONSOLIDATION_TITLE = "Daily consolidation"
COLLECT_TITLE = "Collect improvement items"
PROCESS_TITLE = "Process improvement items"
DISK_SPACE_TITLE = "Weekly disk space check"
TASK_LOG_MAINTENANCE_TITLE = "Task log maintenance"


REFLECTION_BRIEF = """\
You wake once a week to review recent activity and propose core-memory \
updates worth saving.

## Look back in detail

Find the previous completed Weekly reflection and use its `completed_at` \
as the start of the window; if none exists, use roughly one day ago. \
Review main-chat and task activity since then. Read the actual conversation \
for the few most relevant tasks before inferring anything from a title.

## Think across abstraction levels

Core memory (`about_user.md` and `behavior.md`, already loaded into your \
system prompt above) can hold several levels of learning:

- Hard rules — "never X".
- Gentler preferences — "lean toward Y when there's a choice".
- Role / attribute facts about the user — "background: data scientist", \
"lives in Berlin".
- Meta-patterns — "phrases requests as questions when uncertain", \
"prefers fewer options to more".

When you spot something, don't lock onto the most specific framing. One \
observation often supports more than one framing. A rejected nut-heavy \
recipe might mean "no nuts", "lean toward lighter food", or "I'm suggesting \
too narrow a range". Pick the framing that generalises without overfitting.

## Propose updates via choice

For each candidate update, call `ask_user_choice` with 2–4 phrasings at \
different abstraction levels plus "skip". Leave `allow_free_text=True` so \
the user can word it themselves.

The user's pick comes back as their next message (the tool reassigns to \
the user automatically). Then:

- Draft the *full new content* of the file you'd write to (preserving \
everything you want to keep).
- Show it in the chat.
- Call `ask_user_choice("Save this version?", ["Save", "Edit it", \
"Don't save"])` to confirm.
- On "Save", call `save_core_memory(name, body)`. On "Edit it", revise \
per their notes and confirm again. On anything else, drop it.

Move on to the next observation.

## Done

Once every observation is resolved — or you found nothing worth raising \
— call `complete_task`. The task auto-respawns for next week.

Tone: terse, observational, not eager. You're surfacing what you noticed \
and asking if it's worth remembering. Empty reflections are fine — \
saying nothing is better than padding."""


CONSOLIDATION_BRIEF = """\
You wake up once a day to harvest durable bits from yesterday's main \
chat and finished tasks into the knowledge store. The main chat is \
ephemeral for you — anything worth keeping has to land in \
`data/knowledge/` or it's gone from your view.

## What to look at

Find yesterday's main-chat messages and tasks completed in the same window. \
The main chat is the session whose `task_id` is null; in practice it is the \
lowest-id session unless an old install is unusual.

## What to keep

Keep durable signal: facts, preferences, learnings, and follow-ups the user \
mentioned. Skip greetings, one-off chitchat, and anything already captured. \
Prefer fewer, denser notes over many small ones; duplicate-note pollution is \
the main risk on a daily cadence.

Merge into an existing related knowledge note when one fits; otherwise \
create a note under a sensible folder. Skip items that don't add anything \
to what's already stored.

Call `complete_task` when done. The task auto-respawns for tomorrow.

Tone: terse, observational, low-friction. Saying "nothing notable \
today" and completing the task is a fine outcome on quiet days. Do \
not narrate the process — the chat record is for your own continuity \
across runs, not a report."""


COLLECT_BRIEF = """\
You wake up once a day to scan recent activity for concrete moments \
that should have been captured as improvement items but weren't. \
Improvement items are evidence — discrete moments where the assistant did \
something wrong, inefficient, confusing, or otherwise worth learning \
from.

## Scope

Use roughly the last 24 hours. Review main-chat and task activity in that \
window, reading task chats when their conversation looks relevant.

## What counts

Look for missed learning opportunities: a wrong assumption, tool fumble, \
badly landed answer, inefficient detour, or missed context the user had \
already shared. Skip routine work and anything already captured; check \
existing improvement items, including resolved ones, before creating new \
ones.

For each genuine opportunity, create an improvement item whose description \
stands alone: what happened, what was off, and why it matters. Avoid \
speculative or vague "could be nicer" items.

Quiet day = zero items. Saying nothing is better than padding. \
Call `complete_task` when done; the task auto-respawns for tomorrow.

Tone: terse, observational, evidence-driven. You are not pitching \
fixes here — that's the Process improvement items routine's job. You \
are only collecting evidence."""


PROCESS_BRIEF = """\
You wake up once a day to turn unresolved improvement items into \
concrete suggestions the user can review and apply.

Read and follow the `improve-life-assistant` skill. It gives the context for \
turning evidence into the right kind of durable change: core memory, \
knowledge, or a skill.

Hard rule: do NOT apply suggestions from this routine. Do not call \
`mark_improvement_suggestion_applied`. The Apply step is gated to \
explicit user action via the Improve the assistant panel.

Quiet day = zero new/updated suggestions. Call `complete_task` when \
done; the task auto-respawns for tomorrow."""


DISK_SPACE_BRIEF = """\
You wake once a week to keep an eye on disk space on the host machine \
this assistant runs on. The goal is early warning: catch filesystems, \
inodes, or directories trending toward full before they affect the app \
or host, so the user has time to react.

Inspect usage read-only — never delete, truncate, rotate, compact, or \
otherwise clean up files unless the user has explicitly approved the \
specific cleanup first. Prefer light checks over aggressive scans.

Surface only what matters. If everything looks healthy, say so briefly \
and stop. If something is concerning, name the filesystem or path, the \
current usage, why it matters, and a sensible next step the user can \
weigh in on."""


TASK_LOG_MAINTENANCE_BRIEF = """\
You wake once a week to keep the durable routine logs under \
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

Quiet week = no eligible logs = call `complete_task` with a short \
"nothing to compress" handoff. The routine respawns weekly."""


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
    labels: tuple[str, ...] = field(default_factory=tuple)


# Cadence/time mirrors the old seed migrations: reflection Sun 09:00,
# consolidation 03:00, collect 04:00, process 05:00 (staggered so they
# don't fight for the runner), disk-space Mon 10:00. All UTC.
DEFAULT_ROUTINES: tuple[RoutineSpec, ...] = (
    RoutineSpec(
        key="weekly-reflection",
        title=REFLECTION_TITLE,
        description=REFLECTION_BRIEF,
        interval_unit="week",
        interval_count=1,
        schedule=lambda now: _next_weekday_at(now, weekday=6, hour=9),
    ),
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
        key="process-improvement-items",
        title=PROCESS_TITLE,
        description=PROCESS_BRIEF,
        interval_unit="day",
        interval_count=1,
        schedule=lambda now: _tomorrow_at(now, hour=5),
    ),
    RoutineSpec(
        key="weekly-disk-space-check",
        title=DISK_SPACE_TITLE,
        description=DISK_SPACE_BRIEF,
        interval_unit="week",
        interval_count=1,
        schedule=lambda now: _next_weekday_at(now, weekday=0, hour=10),
        labels=("inbox",),
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
    "weekly-reflection": (REFLECTION_TITLE,),
    "daily-consolidation": (CONSOLIDATION_TITLE,),
    # The production routine drifted to "opportunities" before this ledger
    # existed. Treat that as the same shipped default instead of seeding the
    # canonical title beside it.
    "collect-improvement-items": (COLLECT_TITLE, "Collect improvement opportunities"),
    "process-improvement-items": (PROCESS_TITLE,),
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
    known_label_slugs = set(db.scalars(select(Label.slug)))
    created: list[str] = []
    for spec in DEFAULT_ROUTINES:
        if _default_was_materialized(db, spec):
            continue
        if legacy := _find_legacy_routine(db, spec):
            _record_materialized(db, spec, legacy.id)
            continue
        # `_resolve_labels` raises on an unknown slug; the old disk-space
        # seed only attached `inbox` when that label existed, so filter.
        labels = [s for s in spec.labels if s in known_label_slugs]
        task = create_task(
            db,
            TaskCreate(
                title=spec.title,
                description=spec.description,
                assignee="assistant",
                do_at=spec.schedule(utc_now()),
                interval_unit=spec.interval_unit,
                interval_count=spec.interval_count,
                labels=labels,
            ),
        )
        _record_materialized(db, spec, task.id)
        created.append(spec.title)
    return created
