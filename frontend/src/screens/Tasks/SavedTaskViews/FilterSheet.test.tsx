import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FilterSheet } from "./FilterSheet";

const labels = [
  { id: 1, slug: "home", name: "Home", description: null, color: null, icon: null },
  { id: 2, slug: "review", name: "Review", description: null, color: null, icon: null },
];

describe("FilterSheet", () => {
  it("renders chips for each label", () => {
    render(
      <FilterSheet
        open
        value={{}}
        labels={labels}
        onChange={() => {}}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText("Home")).toBeInTheDocument();
  });

  it("clicking a label chip toggles it", () => {
    const onChange = vi.fn();
    render(
      <FilterSheet
        open
        value={{}}
        labels={labels}
        onChange={onChange}
        onClose={() => {}}
      />,
    );
    fireEvent.click(screen.getByText("Home"));
    expect(onChange).toHaveBeenCalledWith({ labels: ["home"] });
  });

  it("clicking the same chip again removes it", () => {
    const onChange = vi.fn();
    render(
      <FilterSheet
        open
        value={{ labels: ["home"] }}
        labels={labels}
        onChange={onChange}
        onClose={() => {}}
      />,
    );
    fireEvent.click(screen.getByText("Home"));
    expect(onChange).toHaveBeenCalledWith({ labels: [] });
  });
});
