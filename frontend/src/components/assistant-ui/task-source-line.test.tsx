import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { TaskSourceLine } from "./task-source-line";

const metadataRef: { current: unknown } = { current: undefined };

vi.mock("@assistant-ui/react", () => ({
  useAuiState: <T,>(selector: (s: unknown) => T): T =>
    selector({ message: { metadata: metadataRef.current } }),
}));

function renderWithMetadata(metadata: unknown) {
  metadataRef.current = metadata;
  return render(
    <MemoryRouter>
      <TaskSourceLine />
    </MemoryRouter>,
  );
}

describe("TaskSourceLine", () => {
  it("renders a link to the task when source metadata is present", () => {
    renderWithMetadata({
      source: {
        type: "task",
        task_id: 42,
        task_title: "Write the user a haiku",
        source_session_id: 17,
      },
    });

    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/tasks/42");
    expect(link).toHaveAccessibleName(
      "Open source task: Write the user a haiku",
    );
    expect(link).toHaveTextContent("Task notification");
    expect(link).toHaveTextContent("Write the user a haiku");
  });

  it("renders nothing when metadata has no source", () => {
    const { container } = renderWithMetadata({ custom: {} });
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when metadata is undefined", () => {
    const { container } = renderWithMetadata(undefined);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for unrecognized source types", () => {
    const { container } = renderWithMetadata({
      source: { type: "other", task_id: 1 },
    });
    expect(container).toBeEmptyDOMElement();
  });
});
