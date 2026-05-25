import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DescriptionEditor } from "./DescriptionEditor";

describe("DescriptionEditor", () => {
  it("does not render when closed", () => {
    render(
      <DescriptionEditor
        open={false}
        initialValue="x"
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("description-editor")).not.toBeInTheDocument();
  });

  it("Save is disabled until the draft changes, then commits the new value", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(
      <DescriptionEditor
        open
        initialValue="old"
        onSave={onSave}
        onClose={onClose}
      />,
    );

    expect(screen.getByTestId("description-editor-save")).toBeDisabled();

    const area = screen.getByLabelText("Description");
    await userEvent.clear(area);
    await userEvent.type(area, "new");
    await userEvent.click(screen.getByTestId("description-editor-save"));

    expect(onSave).toHaveBeenCalledWith("new");
    expect(onClose).toHaveBeenCalled();
  });

  it("clearing the field saves null (no empty-string descriptions)", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <DescriptionEditor
        open
        initialValue="something"
        onSave={onSave}
        onClose={vi.fn()}
      />,
    );

    await userEvent.clear(screen.getByLabelText("Description"));
    await userEvent.click(screen.getByTestId("description-editor-save"));

    expect(onSave).toHaveBeenCalledWith(null);
  });

  it("Cancel closes without saving", async () => {
    const onSave = vi.fn();
    const onClose = vi.fn();
    render(
      <DescriptionEditor
        open
        initialValue=""
        onSave={onSave}
        onClose={onClose}
      />,
    );

    await userEvent.type(screen.getByLabelText("Description"), "draft");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onClose).toHaveBeenCalled();
    expect(onSave).not.toHaveBeenCalled();
  });
});
