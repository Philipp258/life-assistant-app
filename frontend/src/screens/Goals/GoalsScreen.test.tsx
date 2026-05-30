import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GoalsScreen } from "./GoalsScreen";
import { listGoals } from "./goalsApi";
import type { Goal } from "./goalsApi";

vi.mock("./goalsApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./goalsApi")>();
  return {
    ...actual,
    listGoals: vi.fn(),
    createGoal: vi.fn(),
  };
});

const listGoalsMock = vi.mocked(listGoals);

function makeGoal(overrides: Partial<Goal> = {}): Goal {
  return {
    id: 1,
    title: "Ship goals MVP",
    description: "Goals sit above concrete tasks.",
    is_done: false,
    open_tasks_count: 2,
    done_tasks_count: 1,
    created_at: "2026-05-01T10:00:00Z",
    updated_at: "2026-05-02T10:00:00Z",
    completed_at: null,
    ...overrides,
  };
}

function renderGoals() {
  render(
    <MemoryRouter initialEntries={["/goals"]}>
      <Routes>
        <Route path="/goals" element={<GoalsScreen />} />
        <Route path="/goals/:goalId" element={<div data-testid="goal-detail" />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  listGoalsMock.mockReset();
});

describe("GoalsScreen", () => {
  it("loads active goals and opens a goal detail route", async () => {
    listGoalsMock.mockResolvedValue([makeGoal()]);
    renderGoals();

    expect(await screen.findByText("Ship goals MVP")).toBeInTheDocument();
    expect(screen.getByText(/2 open \/ 1 done/)).toBeInTheDocument();
    expect(listGoalsMock).toHaveBeenCalledWith(false);

    await userEvent.click(screen.getByTestId("goal-card"));
    expect(screen.getByTestId("goal-detail")).toBeInTheDocument();
  });

  it("switches to completed goals", async () => {
    listGoalsMock
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([makeGoal({ is_done: true, completed_at: "2026-05-05T10:00:00Z" })]);
    renderGoals();

    await waitFor(() => expect(listGoalsMock).toHaveBeenCalledWith(false));
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(listGoalsMock).toHaveBeenCalledWith(true));
    expect(await screen.findByText("Ship goals MVP")).toBeInTheDocument();
  });
});
