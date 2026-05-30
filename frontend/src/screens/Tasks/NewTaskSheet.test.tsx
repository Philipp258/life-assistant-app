import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { listGoals } from "@/screens/Goals/goalsApi";

import { NewTaskSheet } from "./NewTaskSheet";

vi.mock("@/shell/identity", () => ({
  useIdentity: () => ({ assistantName: "Peter" }),
}));

vi.mock("@/screens/Goals/goalsApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/screens/Goals/goalsApi")>();
  return {
    ...actual,
    listGoals: vi.fn(),
  };
});

const listGoalsMock = vi.mocked(listGoals);

beforeEach(() => {
  listGoalsMock.mockReset();
  listGoalsMock.mockResolvedValue([
    {
      id: 7,
      title: "Get a dog",
      description: null,
      is_done: false,
      open_tasks_count: 0,
      done_tasks_count: 0,
      created_at: "2026-05-30T08:00:00Z",
      updated_at: "2026-05-30T08:00:00Z",
      completed_at: null,
    },
  ]);
});

describe("NewTaskSheet", () => {
  it("lets users attach a new task to a goal", async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();

    render(
      <NewTaskSheet open onClose={onClose} onCreate={onCreate} />,
    );

    await userEvent.type(await screen.findByLabelText("Title"), "Buy leash");
    const goalSelect = await screen.findByRole("combobox", { name: "Goal" });
    await userEvent.selectOptions(goalSelect, "7");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(onCreate).toHaveBeenCalledWith({
        title: "Buy leash",
        description: null,
        assignee: "user",
        goal_id: 7,
      });
    });
    expect(onClose).toHaveBeenCalled();
  });
});
