# 006 — I need to do the dishes

## Scenario

User says (no specific time, no deadline):

> I need to do the dishes.

## Expected user-visible behavior

- the assistant recognizes a plain user todo with no dates.
- Creates row: `assignee="user"`, no do_at, no due_at.
- the assistant's reply: short ack, e.g. "Added to your todos."
- TasksScreen "Todos" section shows the row with the most plain UI possible — title + checkbox.
- User checks the box when done.

## Expected row shape

```
title:          "Do the dishes"
description:    null (or empty)
assignee:       "user"
do_at:          null
due_at:         null
interval_unit:  null
interval_count: null
```

Computed kind: `todo`.

## Lifecycle

- Row created. State = `yours`.
- No watchdog activity, no scheduled wake.
- User completes via UI checkbox → done.

## Surprising / open questions

- This is the most boring case but matters as a baseline: the system shouldn't over-engineer for it. No chat noise, no schedule, no the assistant involvement past creation.
- the assistant must avoid asking unnecessary clarifying questions ("when?", "is it urgent?") — for a plain "I need to" the right move is just record and ack.
