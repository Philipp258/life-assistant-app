"""Goals API and agent-tool behavior."""

from __future__ import annotations

import pytest

from app.agent.tools.goals import (
    do_append_goal_event,
    do_create_goal,
    do_get_goal,
    do_list_goals,
    do_update_goal,
)
from app.agent.tools.tasks import do_create_task


def test_goals_api_create_list_detail_complete_reopen(client):
    task = client.post("/api/tasks", json={"title": "Pick first step"}).json()

    created = client.post(
        "/api/goals",
        json={
            "title": "Ship goals MVP",
            "description": "A simple goal layer above tasks.",
            "task_ids": [task["id"]],
        },
    )
    assert created.status_code == 201
    goal = created.json()
    assert goal["title"] == "Ship goals MVP"
    assert goal["description"] == "A simple goal layer above tasks."
    assert goal["is_done"] is False
    assert goal["open_tasks_count"] == 1
    assert goal["done_tasks_count"] == 0

    listed = client.get("/api/goals?done=false")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()["goals"]] == [goal["id"]]

    detail = client.get(f"/api/goals/{goal['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["tasks"][0]["id"] == task["id"]
    assert body["tasks"][0]["goal_title"] == "Ship goals MVP"
    assert {"created", "task_linked"}.issubset({event["kind"] for event in body["events"]})

    completed = client.patch(f"/api/goals/{goal['id']}", json={"is_done": True})
    assert completed.status_code == 200
    assert completed.json()["is_done"] is True
    assert completed.json()["completed_at"] is not None

    reopened = client.patch(f"/api/goals/{goal['id']}", json={"is_done": False})
    assert reopened.status_code == 200
    assert reopened.json()["is_done"] is False
    assert reopened.json()["completed_at"] is None
    assert {"completed", "reopened"}.issubset(
        {event["kind"] for event in reopened.json()["events"]}
    )


def test_goals_api_rejects_unknown_linked_task(client):
    r = client.post("/api/goals", json={"title": "Bad link", "task_ids": [9999]})
    assert r.status_code == 400
    assert "unknown task_id" in r.json()["detail"]


def test_goals_api_delete_unlinks_tasks(client):
    goal = client.post("/api/goals", json={"title": "Temporary goal"}).json()
    task = client.post(
        "/api/tasks",
        json={"title": "Keep this task", "goal_id": goal["id"]},
    ).json()

    deleted = client.delete(f"/api/goals/{goal['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/goals/{goal['id']}").status_code == 404

    kept_task = client.get(f"/api/tasks/{task['id']}")
    assert kept_task.status_code == 200
    assert kept_task.json()["goal_id"] is None
    assert kept_task.json()["goal_title"] is None


def test_task_goal_linking_and_completion_appends_goal_events(client):
    goal = client.post("/api/goals", json={"title": "Finish project"}).json()

    created = client.post(
        "/api/tasks",
        json={"title": "Do the concrete step", "goal_id": goal["id"]},
    )
    assert created.status_code == 201
    task = created.json()
    assert task["goal_id"] == goal["id"]
    assert task["goal_title"] == "Finish project"

    done = client.patch(f"/api/tasks/{task['id']}", json={"is_done": True})
    assert done.status_code == 200

    detail = client.get(f"/api/goals/{goal['id']}").json()
    kinds = [event["kind"] for event in detail["events"]]
    assert "task_linked" in kinds
    assert "task_completed" in kinds
    assert detail["open_tasks_count"] == 0
    assert detail["done_tasks_count"] == 1

    reopened = client.patch(f"/api/tasks/{task['id']}", json={"is_done": False})
    assert reopened.status_code == 200
    detail = client.get(f"/api/goals/{goal['id']}").json()
    assert "task_reopened" in [event["kind"] for event in detail["events"]]


def test_task_goal_update_moves_event_log_between_goals(client):
    first = client.post("/api/goals", json={"title": "First goal"}).json()
    second = client.post("/api/goals", json={"title": "Second goal"}).json()
    task = client.post(
        "/api/tasks",
        json={"title": "Move me", "goal_id": first["id"]},
    ).json()

    moved = client.patch(f"/api/tasks/{task['id']}", json={"goal_id": second["id"]})
    assert moved.status_code == 200
    assert moved.json()["goal_id"] == second["id"]
    assert moved.json()["goal_title"] == "Second goal"

    first_events = client.get(f"/api/goals/{first['id']}").json()["events"]
    second_events = client.get(f"/api/goals/{second['id']}").json()["events"]
    assert "task_unlinked" in [event["kind"] for event in first_events]
    assert "task_linked" in [event["kind"] for event in second_events]

    cleared = client.patch(f"/api/tasks/{task['id']}", json={"goal_id": None})
    assert cleared.status_code == 200
    assert cleared.json()["goal_id"] is None
    second_events = client.get(f"/api/goals/{second['id']}").json()["events"]
    assert "task_unlinked" in [event["kind"] for event in second_events]


@pytest.mark.usefixtures("_test_db")
def test_goal_agent_tools_cover_mvp_flow():
    goal = do_create_goal("Ship goals MVP", description="Keep it simple.")
    assert "error" not in goal
    task = do_create_task(title="Write goal tests", assignee="assistant", goal_id=goal["id"])
    assert "error" not in task
    assert task["goal_title"] == "Ship goals MVP"

    listed = do_list_goals(is_done=False, title="goals")
    assert listed["total"] == 1
    assert listed["goals"][0]["id"] == goal["id"]

    detail = do_get_goal(goal["id"])
    assert detail["tasks"][0]["id"] == task["id"]

    note = do_append_goal_event(goal["id"], body="Tests started.")
    assert note["kind"] == "note"
    assert note["body"] == "Tests started."

    completed = do_update_goal(goal["id"], is_done=True)
    assert completed["is_done"] is True
    assert completed["completed_at"] is not None
