import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ManageLabelsSheet } from "./ManageLabelsSheet";

vi.mock("./labelsApi", () => ({
  listLabels: vi.fn().mockResolvedValue([
    {
      id: 1,
      slug: "home",
      name: "Home",
      description: null,
      color: null,
      icon: null,
    },
  ]),
  createLabel: vi.fn().mockResolvedValue({
    id: 2,
    slug: "x",
    name: "X",
    description: null,
    color: null,
    icon: null,
  }),
  updateLabel: vi.fn(),
  deleteLabel: vi.fn().mockResolvedValue(undefined),
}));

describe("ManageLabelsSheet", () => {
  it("lists existing labels", async () => {
    render(<ManageLabelsSheet open onClose={() => {}} />);
    expect(await screen.findByText("Home")).toBeInTheDocument();
  });

  it("calls createLabel when form submitted", async () => {
    const { createLabel } = await import("./labelsApi");
    render(<ManageLabelsSheet open onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/slug/i), {
      target: { value: "x" },
    });
    fireEvent.change(screen.getByPlaceholderText(/name/i), {
      target: { value: "X" },
    });
    fireEvent.click(screen.getByRole("button", { name: /add label/i }));
    await screen.findByText("X");
    expect(createLabel).toHaveBeenCalledWith({ slug: "x", name: "X" });
  });
});
