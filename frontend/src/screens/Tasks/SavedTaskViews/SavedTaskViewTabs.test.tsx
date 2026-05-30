import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SavedTaskViewTabs } from "./SavedTaskViewTabs";

const views = [
  {
    id: 1,
    name: "Today",
    icon: "☀️",
    filters: {},
    group_by: "none" as const,
    sort_index: 0,
    is_default: true,
  },
  {
    id: 2,
    name: "Mine",
    icon: "👤",
    filters: { assignee: "user" as const },
    group_by: "none" as const,
    sort_index: 1,
    is_default: false,
  },
];

describe("SavedTaskViewTabs", () => {
  it("renders each view as a pill", () => {
    render(
      <SavedTaskViewTabs
        views={views}
        activeId={1}
        dirty={false}
        onSelect={() => {}}
        onRename={() => {}}
        onMakeDefault={() => {}}
        onDelete={() => {}}
        onReorder={() => {}}
        onAdd={() => {}}
      />,
    );
    expect(screen.getByText("Today")).toBeInTheDocument();
    expect(screen.getByText("Mine")).toBeInTheDocument();
  });

  it("clicking inactive tab calls onSelect", () => {
    const onSelect = vi.fn();
    render(
      <SavedTaskViewTabs
        views={views}
        activeId={1}
        dirty={false}
        onSelect={onSelect}
        onRename={() => {}}
        onMakeDefault={() => {}}
        onDelete={() => {}}
        onReorder={() => {}}
        onAdd={() => {}}
      />,
    );
    fireEvent.click(screen.getByText("Mine"));
    expect(onSelect).toHaveBeenCalledWith(2);
  });

  it("clicking active tab opens portal menu and Rename triggers callback", async () => {
    const onRename = vi.fn();
    render(
      <SavedTaskViewTabs
        views={views}
        activeId={1}
        dirty={false}
        onSelect={() => {}}
        onRename={onRename}
        onMakeDefault={() => {}}
        onDelete={() => {}}
        onReorder={() => {}}
        onAdd={() => {}}
      />,
    );
    fireEvent.click(screen.getByText("Today"));
    fireEvent.click(await screen.findByText("Rename"));
    const input = screen.getByLabelText("Rename view") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Day plan" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onRename).toHaveBeenCalledWith(1, "Day plan");
  });

  it("Move right in the active-tab menu reorders the tabs", async () => {
    const onReorder = vi.fn();
    render(
      <SavedTaskViewTabs
        views={views}
        activeId={1}
        dirty={false}
        onSelect={() => {}}
        onRename={() => {}}
        onMakeDefault={() => {}}
        onDelete={() => {}}
        onReorder={onReorder}
        onAdd={() => {}}
      />,
    );
    fireEvent.click(screen.getByText("Today"));
    fireEvent.click(await screen.findByText(/Move right/));
    expect(onReorder).toHaveBeenCalledWith([2, 1]);
  });

  it("renders the first letter when icon is null", () => {
    const noIcon = {
      id: 3,
      name: "Errands",
      icon: null,
      filters: {},
      group_by: "none" as const,
      sort_index: 2,
      is_default: false,
    };
    render(
      <SavedTaskViewTabs
        views={[noIcon]}
        activeId={3}
        dirty={false}
        onSelect={() => {}}
        onRename={() => {}}
        onMakeDefault={() => {}}
        onDelete={() => {}}
        onReorder={() => {}}
        onAdd={() => {}}
      />,
    );
    expect(screen.getByText("E")).toBeInTheDocument();
  });
});
