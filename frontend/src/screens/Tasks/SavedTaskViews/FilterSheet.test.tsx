import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FilterSheet } from "./FilterSheet";

describe("FilterSheet", () => {
  it("renders owner, status, and date filters", () => {
    render(
      <FilterSheet
        open
        value={{}}
        onChange={() => {}}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText("Owner")).toBeInTheDocument();
    expect(screen.getByText("Status")).toBeInTheDocument();
    expect(screen.getByText("Date")).toBeInTheDocument();
  });

  it("clicking an owner chip updates the assignee filter", () => {
    const onChange = vi.fn();
    render(
      <FilterSheet
        open
        value={{}}
        onChange={onChange}
        onClose={() => {}}
      />,
    );
    fireEvent.click(screen.getByText("Mine"));
    expect(onChange).toHaveBeenCalledWith({ assignee: "user" });
  });

  it("clicking a status chip toggles it", () => {
    const onChange = vi.fn();
    render(
      <FilterSheet
        open
        value={{}}
        onChange={onChange}
        onClose={() => {}}
      />,
    );
    fireEvent.click(screen.getByText("Open"));
    expect(onChange).toHaveBeenCalledWith({ statuses: ["open"] });
  });
});
