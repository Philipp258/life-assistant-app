# 09 — Skill lifecycle

Status: yellow
Severity: friction

What I tried: asked the assistant to install a tiny user skill named `release-test-motto`, inspected it in Agent → Memory → Skills, then started a fresh chat and asked for the release test motto.

What worked: the assistant created an `Install release-test-motto skill` task and installed the skill. The skill appeared in the Skills list with source-style read-only presentation and the expected content. In a fresh chat, asking `release test motto` produced the exact expected answer: `ship small, test real`.

Friction: the assistant created a task for the trivial motto response before answering. It still answered correctly, but "Working on it" for a one-line skill response felt heavier than necessary.

Rating: skill install, inspection, and use worked; activation behavior was a little awkward.
