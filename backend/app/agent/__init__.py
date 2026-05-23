"""The chat agent + its tools. Built lazily so imports don't need creds."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model

from app.agent.deps import AgentDeps
from app.agent.safe_tools import install as install_safe_tools
from app.agent.providers.codex import build_codex_model
from app.agent.providers.openai import build_openai_model
from app.agent.providers.openrouter import build_openrouter_model
from app.agent.providers.zai import DEFAULT_ZAI_ENDPOINT, build_zai_model
from app.agent.tools import archived_messages as archived_message_tools
from app.agent.tools import chats as chat_tools
from app.datetime_utils import serialize_utc
from app.agent.tools import fs as fs_tools
from app.agent.tools import knowledge as knowledge_tools
from app.agent.tools import onboarding as onboarding_tools
from app.agent.tools import sessions as session_tools
from app.agent.tools import self_update as self_update_tools
from app.agent.tools import settings as settings_tools
from app.agent.tools import shell as shell_tools
from app.agent.tools import tasks as task_tools
from app.agent.tools import web as web_tools
from app.knowledge import core as core_memory
from app.knowledge import identity as identity_resolver
from app.knowledge import store as knowledge_store
from app.skills import store as skills_store
from app.users import service as users_service

if TYPE_CHECKING:
    from app.tasks.models import Task

_agent: Agent[AgentDeps, str] | None = None


APP_CONTEXT_PROMPT = """\
## App context

You are {assistant_identity}.

Life Assistant has chats, tasks, knowledge notes, core memory, and skills. \
Main chat is for conversation and coordination; task chats hold focused work. \
Tasks, knowledge notes, and core memory are durable sources of truth; chat \
scrollback is conversational context."""


TASK_LINK_PROMPT = """\
## App links

When mentioning a task in a user-facing message, link it as Markdown: \
`[<task title>](/tasks/<id>)`. Use bare `/tasks/<id>` only when Markdown \
would be awkward.

When mentioning a knowledge note in a user-facing message, link it as \
Markdown using the public app route: `[<note title>](/know/open/<path>)`. \
Encode each path segment for a URL, e.g. \
`[Projects/Life Assistant MVP Roadmap.md](/know/open/Projects/Life%20Assistant%20MVP%20Roadmap.md)`. \
Do not emit `knowledge://...` links."""


GENERAL_PROMPT = """\
## Main chat

Main chat exists so the user has one foreground conversation while task chats \
do focused work. Talk with the user, relay work to tasks, communicate task \
results, blockers, and questions, and do nothing else.

When the user answers or redirects a running task, use \
`relay_to_task(task_id, note)`; ask if the target task is unclear.

Main chat coordinates task work; it should not supervise task execution by \
watching task chats. Task chats report back through lifecycle handoffs."""


# Tools are scoped by mutation/egress, not raw/not-raw: inspect tools are
# local, instant, side-effect-free and stay available in main chat so it
# can ground answers before delegating; act tools mutate the repo or reach
# out and are gated to task chats via `prepare=only_in_task_chat`. The
# prompts below state the situation only — the why lives here, not in the
# agent's context window.
INSPECT_TOOLS_PROMPT = """\
## Inspecting files

`read_file`, `glob_files`, `grep` — read and search the repo without \
changing it. Cwd is the repo root."""


ACT_TOOLS_PROMPT = """\
## Work tools

Task chats can change things and reach outside the app with `bash` (no \
sandbox), `write_file`, `edit_file`, `web_search` (Brave), and `web_fetch`.

Do not touch `data/*.db*`; that is the live SQLite store. `bash` output is \
capped at 30000 chars per stream.

When web research is blocked — for example `web_search` reports a missing \
Brave API key, or `web_fetch` hits 403/consent/JavaScript-cookie gates — \
do not go silent and do not emit an empty response. Tell the user what \
blocked you, answer from available context if you can label it as such, and \
ask how they want to proceed if live research is still needed (e.g. provide \
a source, enable/configure search, or let you try another route)."""


TASK_PROMPT = """\
## This task

This chat belongs to one task. You are the autonomous task instance: gather \
what you need and do the work here. This is not the user's main chat; text \
you write here stays in the task chat. The main-chat assistant owns the \
foreground conversation.

End the task with the terminal move that matches reality: `complete_task` \
when done, `reassign_task(assignee='user')` when you need input or a \
decision, or `reschedule_task` when the right next move is to wait. Each \
terminal move needs a `handoff` for the main-chat assistant: what happened, \
what is needed, or why you are waiting. The handoff is hidden context, not a \
direct user message. If main chat later relays an answer with \
`relay_to_task`, treat it as user intent for this task."""


TASK_LOG_PROMPT = """\
## Task log

This routine has a durable knowledge note at the `task_log` path above. It \
carries context across cycles; each cycle still gets a fresh task chat.

Always read it at the start of the cycle. Before completing the cycle, save \
only notes that will help future cycles: relevant outcomes, corrections, \
recurring friction, and lessons or suggestions worth trying next time. Keep \
it scoped to this routine."""


ONBOARDING_PROMPT = """\
## What this is

A short setup ritual. The user names you, tells you who they are, and explains how they want you to behave. Save the durable parts into core memory; chat scrollback is not memory. When both core files reflect the conversation and setup feels complete, call `mark_onboarded` once. The next turn switches to normal mode.

## What "done" looks like

1. `data/core/behavior.md` — first non-empty line is exactly `**Name:** <X>` where `<X>` is the name the user picked for you. Followed by 1–4 lines on tone/style/how-to-act, in the user's own words.
2. `data/core/about_user.md` — at minimum: the user's own name + one fact about them (what they do, what matters, how they intend to use you).

## How to run it

Read the user's reply to the greeting; they named you in it. Use that name from now on. Ask their own name, then 1–2 open questions about work, interests, or how they want you to behave. Save facts as they arrive with `save_core_memory`, rewriting each file as you learn more. Keep replies short; this is setup, not a general chat.

This conversation is narrow on purpose. Don't create tasks, edit knowledge, run shell tools, or promise capabilities — the user discovers those after onboarding ends. Don't call `mark_onboarded` before both files are written.
"""


VOICE_MODE_PROMPT = """\
The user is interacting through voice mode: your reply will be spoken aloud \
by TTS, not read on screen. Answer in a concise, conversational style — \
short sentences, plain prose, no Markdown tables or code blocks unless \
strictly necessary. Skip long URLs and verbose lists; lead with the answer, \
add detail only if useful."""


IMPROVE_ASSISTANT_PROMPT = """\
You can capture concrete moments worth learning from with \
`create_task(labels=['improve-life-assistant'], assignee='assistant', \
description=<evidence>)` — anywhere, in any chat. Use it when you notice \
you did something wrong, inefficient, confusing, or worth doing better next \
time. Description is evidence ONLY: what happened, what was off, why it \
matters.

Do not propose the fix here — the spawned task's own agent proposes a \
persistent change, asks the user to confirm, and applies it (it follows the \
`improve-life-assistant` skill). Skip vague or speculative observations; only \
file something concrete and actionable. The daily *Collect improvement \
opportunities* routine sweeps for things you missed."""


# Cross-cutting concept doc — appended to both GENERAL_PROMPT and
# TASK_PROMPT. Describes what tasks can do, including the surprising
# behaviors the agent can't infer from tool signatures alone.
HOW_TASKS_WORK = """## How tasks work

Fields:
- title, description: free-form context for the run. Editable via `update_task` (e.g. when the user refines what they want).
- assignee: 'assistant' = autonomous loop in this task's chat. 'user' = paused, ball in user's court.
- do_at: START trigger. The runner only wakes an assistant-assigned task once `do_at <= now`. Use this for scheduled jobs and reminders ("Saturday 9am: groceries" → do_at=Sat 09:00, assignee='assistant').
- due_at: DEADLINE. User-facing only — the runner ignores it. Use for "by tomorrow", "before Friday". Surface it in your messages so the user knows you remember the deadline.
- interval_unit + interval_count: recurrence. On `complete_task`, a NEW task row + NEW chat session is auto-spawned with do_at = prev do_at + interval. Completing a recurring task does NOT mean "done forever"; it means "this cycle done, next one queued".
- chat_session_id: every task has its own chat. Chat persists after completion; you can read prior cycles via `list_chat_messages`.

Ownership:
- If the user says they need to do something ("I need to write a letter"), create a user-owned todo or deadline.
- If the user asks you to do something ("write the letter", "research this"), create or run an assistant-owned job.

Surprising behaviors you can't infer from tool signatures:
- A watchdog re-wakes you every ~60s while assignee='assistant' and you're not done. If you have nothing left to do but aren't ready to finish, stay quiet — don't pad. Eventually call `reassign_task('user', handoff=...)`, `complete_task(handoff=...)`, or `reschedule_task(do_at=..., handoff=...)`.
- The terminal task tools do NOT post anything to the user's main chat. They record your plain-text handoff; the main-chat assistant is then woken with that handoff and decides whether to update main chat or stay silent.
- The user can edit task fields mid-run. Re-read fresh task data on each wake; don't assume description is static.
- Reassign user→assistant happens silently when the user re-engages. This can happen from the task chat or from main chat: the main-chat agent relays the user's answer with `relay_to_task`, which writes it into the task chat and resumes the task.
- Recurrence spawns a fresh chat per cycle. You won't see prior cycles' chat unless you call `list_chat_messages` on them via `get_task` to find the old session id.
- When the user asks for "remind me Saturday morning", that's a one-shot scheduled-job: assignee='assistant', do_at=Sat 09:00, no interval. When you wake at do_at, call `complete_task(handoff=...)` with the reminder text and any context the main-chat assistant needs to decide what to tell the user.

Computed kind (what the user sees in the UI; not stored on the row):
- assignee='user', due_at set                      → "deadline"
- assignee='user', do_at set (no due_at)           → "scheduled todo"
- assignee='user', neither                         → "todo"
- assignee='assistant', interval set               → "routine"
- assignee='assistant', do_at set (one-shot)       → "scheduled job"
- assignee='assistant', no dates                   → "job"

Speak in the user's vocabulary: "I'll remind you Saturday" not "I created a task". "Routine running every morning". "Working on it" for jobs. "Noted, due Friday" for deadlines."""


KNOWLEDGE_BLURB = """\
## Knowledge

Paths and titles of knowledge entries under data/knowledge/. Open entries \
with `read_knowledge(path)`. When the user asks you to remember or forget \
something, use the knowledge tools instead of raw filesystem edits."""


SKILLS_BLURB = """\
## Skills

Installed agent skills. Each entry below lists the skill's name, \
description, and the path to its SKILL.md — read that exact path with \
`read_file` to activate the skill before invoking it. Default skills live \
under `backend/defaults/skills/<name>/` and are read-only; user-installed \
skills live under `data/skills/<name>/`. To install or update skills, \
follow the `add-skills` skill."""


SKILLS_BLURB_MAIN = """\
## Skills

Installed skills below (name, description, SKILL.md path). To use one, \
create a task — skills activate and run in the task chat, not here."""


def build_chat_model() -> Model:
    """The configured chat model. Used by the main agent and by
    one-shot helpers (e.g. main-chat compaction's summarizer).

    Honours the user's `preferred_chat_provider`; falls back to the
    hardcoded order if unset or pointing at an unconfigured provider.
    """
    # Local import: the picker reaches back into `app.agent` via
    # `invalidate_agent`, so import it lazily to keep that cycle off the
    # module-load path.
    from app.db import SessionLocal
    from app.provider_settings import service as provider_service

    with SessionLocal() as db:
        pick = provider_service.pick_chat(db)

    if pick.provider == "openai":
        assert pick.openai_api_key is not None
        return build_openai_model(api_key=pick.openai_api_key, model_name=pick.model_name)
    if pick.provider == "openrouter":
        assert pick.openrouter_api_key is not None
        return build_openrouter_model(api_key=pick.openrouter_api_key, model_name=pick.model_name)
    if pick.provider == "zai":
        assert pick.zai_api_key is not None
        endpoint = pick.zai_endpoint or DEFAULT_ZAI_ENDPOINT
        return build_zai_model(
            api_key=pick.zai_api_key, model_name=pick.model_name, endpoint=endpoint
        )
    if pick.provider == "codex":
        assert pick.codex_auth_json is not None
        return build_codex_model(
            auth_blob=pick.codex_auth_json,
            model_name=pick.model_name,
            persist=provider_service.persist_codex_auth,
        )
    raise RuntimeError(f"Unsupported chat provider: {pick.provider}")


def _task_for_session(session_id: int | None) -> Task | None:
    """Return the Task this chat belongs to, or None for general chats."""
    if session_id is None:
        return None
    # Local import avoids a cycle (chat.models → db → app config at import).
    from app.chat.models import ChatSession
    from app.db import SessionLocal
    from app.tasks.models import Task

    with SessionLocal() as db:
        chat = db.get(ChatSession, session_id)
        if chat is None or chat.task_id is None:
            return None
        return db.get(Task, chat.task_id)


def _session_kind(session_id: int | None) -> str:
    """Return 'main' | 'task' (or any other persisted kind). Defaults
    to 'main' for None.

    Used by the system-prompt builder to pick which preamble to inject.
    """
    if session_id is None:
        return "main"
    from app.chat.models import ChatSession
    from app.db import SessionLocal

    with SessionLocal() as db:
        chat = db.get(ChatSession, session_id)
        if chat is None:
            return "main"
        return chat.kind


def build_system_prompt(session_id: int | None, *, voice_mode: bool = False) -> str:
    """Render the full system prompt for a given chat session.

    Pulled out of the Agent's closure so tests can call it directly
    with a session id instead of wiring up a pydantic-ai run context.

    The role preamble is the only kind-specific section: a task chat
    gets the autonomous `TASK_PROMPT` (plus the task's identity); the
    main chat gets the conversational `GENERAL_PROMPT`. The main chat
    surfaces finished/blocked task work conversationally — task-terminal
    events arrive as a synthetic user-role report on a normal main turn
    (`app.chat.events`); there is no separate handoff prompt or agent.

    `voice_mode=True` appends a small spoken-style instruction at the
    very end of the prompt. Placement matters: provider prompt caches
    work best on identical leading-token prefixes, so the
    stable portion (app context + kind preamble + tasks doc + memory + tree +
    skills) must stay byte-identical across voice/non-voice turns. Only
    the tail diverges when the flag flips.
    """
    name = identity_resolver.resolve_assistant_name()
    kind = _session_kind(session_id)

    # Onboarding mode: fresh user, main session, flag unset. Strip down
    # to the ritual prompt plus shared app context — no shell tools doc, no
    # tasks doc, no knowledge tree. Core memory still injected verbatim so
    # the agent sees its own writes mid-ritual. Restricted to the main
    # session; task chats run with their normal prompts even pre-flag, which is
    # fine because they don't normally trigger pre-onboarding.
    task = _task_for_session(session_id)
    if task is None and kind == "main" and users_service.is_onboarding():
        about = core_memory.read(core_memory.ABOUT_USER).rstrip()
        behavior = core_memory.read(core_memory.BEHAVIOR).rstrip()
        onboarding_sections = [
            ONBOARDING_PROMPT,
            APP_CONTEXT_PROMPT.format(
                assistant_identity=(
                    "a brand-new assistant in your first conversation with the user; "
                    "you have no name yet"
                )
            ),
            "## About you (current contents — you will overwrite)",
            about,
            "## How to behave (current contents — you will overwrite)",
            behavior,
        ]
        # Same invariant as the non-onboarding path below: the voice
        # marker goes last so the cached prefix stays byte-identical
        # across voice/non-voice turns even mid-onboarding. Without this
        # a voice user in the onboarding ritual got the text-style
        # prompt, and the prompt was identical with/without the flag.
        if voice_mode:
            onboarding_sections.extend(["## Voice mode", VOICE_MODE_PROMPT])
        return "\n\n".join(onboarding_sections)

    app_context = APP_CONTEXT_PROMPT.format(
        assistant_identity=(
            f"{name}, the assistant inside Life Assistant: "
            "a personal-assistant app the user runs for themselves"
        )
    )

    # The role section is a kind-specific preamble, each
    # carrying its own `##` heading. The shared app context comes first so
    # every normal agent mode starts from the same model of how the app fits
    # together, then the role section narrows what this turn is for. Task
    # chats also embed the task identity under that heading so the agent
    # calls tools with the right id (without this, models hallucinate task_ids
    # and have completed unrelated tasks).
    exposes_task_log = False
    if task is not None:
        fields = [f"- task_id: {task.id}", f"- title: {task.title}"]
        if task.description and task.description.strip():
            fields.append(f"- description: {task.description.strip()}")
        if task.do_at is not None:
            fields.append(f"- do_at: {serialize_utc(task.do_at)}")
        if task.due_at is not None:
            fields.append(f"- due_at: {serialize_utc(task.due_at)}")
        from app.tasks.task_log import should_expose_task_log

        task_log_line = task.task_log_line
        exposes_task_log = should_expose_task_log(task_log_line=task_log_line)
        if exposes_task_log and task_log_line is not None:
            from app.tasks.task_log import task_log_path

            fields.append(f"- task_log: {task_log_path(task_log_line)}")
        role = TASK_PROMPT + "\n\n" + "\n".join(fields)
    else:
        role = GENERAL_PROMPT

    # Always-loaded core memory (verbatim).
    about = core_memory.read(core_memory.ABOUT_USER).rstrip()
    behavior = core_memory.read(core_memory.BEHAVIOR).rstrip()

    # Live walk of the knowledge dir; cheap for a personal-scale store.
    tree_blob = knowledge_store.render_tree_for_prompt(knowledge_store.walk_tree())

    # Skills footer: compact list, agent reads full body via read_file
    # on demand. Kept near the end so the prompt prefix stays cache-stable.
    skills_blob = skills_store.render_skills_for_prompt(skills_store.list_skills())

    common_tail = [
        TASK_LINK_PROMPT,
        HOW_TASKS_WORK,
        f"## Improving {name}\n\n{IMPROVE_ASSISTANT_PROMPT}",
        f"## About you\n\n{about}",
        f"## How to behave\n\n{behavior}",
        f"{KNOWLEDGE_BLURB}\n\n{tree_blob}",
    ]
    if task is not None:
        sections = [
            app_context,
            role,
            INSPECT_TOOLS_PROMPT,
            ACT_TOOLS_PROMPT,
            *common_tail,
            f"{SKILLS_BLURB}\n\n{skills_blob}",
        ]
        # Recurring routines get the task-log instructions inline. Placed
        # after the common tail so the cache prefix for every task chat
        # without a log line stays byte-identical.
        if exposes_task_log:
            sections.append(TASK_LOG_PROMPT)
    else:
        sections = [
            app_context,
            role,
            INSPECT_TOOLS_PROMPT,
            *common_tail,
            f"{SKILLS_BLURB_MAIN}\n\n{skills_blob}",
        ]
    # Voice-mode marker goes last so the cached prefix above is
    # byte-identical to non-voice turns — only the tail diverges.
    if voice_mode:
        sections.append(f"## Voice mode\n\n{VOICE_MODE_PROMPT}")
    return "\n\n".join(sections)


def _build_agent() -> Agent[AgentDeps, str]:
    agent: Agent[AgentDeps, str] = Agent(
        build_chat_model(),
        deps_type=AgentDeps,
    )
    # Wrap tool registrations so an uncaught exception from any tool
    # becomes structured `{"error": "..."}` feedback to the model
    # instead of aborting the assistant turn. Must be installed before
    # any tool is registered.
    install_safe_tools(agent)

    @agent.system_prompt
    def system_prompt(ctx: RunContext[AgentDeps]) -> str:
        sid = ctx.deps.session_id if ctx.deps is not None else None
        voice = ctx.deps.voice_mode if ctx.deps is not None else False
        return build_system_prompt(sid, voice_mode=voice)

    @agent.tool_plain
    def now(timezone: str = "UTC") -> str:
        """Return the current time as an ISO 8601 string in the given timezone."""
        from zoneinfo import ZoneInfo

        try:
            tz = ZoneInfo(timezone)
        except Exception:
            tz = ZoneInfo("UTC")
        return datetime.now(tz).isoformat()

    task_tools.register(agent)
    chat_tools.register(agent)
    session_tools.register(agent)
    archived_message_tools.register(agent)
    knowledge_tools.register(agent)
    shell_tools.register(agent)
    fs_tools.register(agent)
    web_tools.register(agent)
    self_update_tools.register(agent)
    settings_tools.register(agent)
    onboarding_tools.register(agent)

    return agent


def get_agent() -> Agent[AgentDeps, str]:
    global _agent
    if _agent is None:
        _agent = _build_agent()
    return _agent


def invalidate_agent() -> None:
    """Drop the cached agent so the next get_agent() rebuilds it.

    Called whenever provider config changes — the agent embeds the
    pydantic-ai model with baked-in API key, so a config change must
    rebuild the whole agent.
    """
    global _agent
    _agent = None
