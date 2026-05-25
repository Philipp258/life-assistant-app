import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SkillView } from "./SkillView";

vi.mock("./knowledgeApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./knowledgeApi")>();
  return {
    ...actual,
    fetchSkill: vi.fn(),
  };
});

import { fetchSkill } from "./knowledgeApi";

const fetchSkillMock = vi.mocked(fetchSkill);

beforeEach(() => {
  fetchSkillMock.mockReset();
});

describe("SkillView", () => {
  it("renders body as markdown", async () => {
    fetchSkillMock.mockResolvedValueOnce({
      name: "add-skills",
      description: "Install agent skills.",
      path: "data/skills/add-skills/SKILL.md",
      source: "default",
      body: "# Heading\n\nSome body content.",
    });

    render(<SkillView name="add-skills" onBack={vi.fn()} />);

    await waitFor(() =>
      expect(screen.getByText("Heading")).toBeInTheDocument(),
    );
    expect(screen.getByText("Some body content.")).toBeInTheDocument();
  });

  it("shows the read-only banner", async () => {
    fetchSkillMock.mockResolvedValueOnce({
      name: "foo",
      description: "x",
      path: "data/skills/foo/SKILL.md",
      source: "user",
      body: "hi",
    });

    render(<SkillView name="foo" onBack={vi.fn()} />);

    await waitFor(() =>
      expect(
        screen.getByText(/Read-only.*Chat tab/i),
      ).toBeInTheDocument(),
    );
  });

  it("does not render edit/delete/save controls", async () => {
    fetchSkillMock.mockResolvedValueOnce({
      name: "foo",
      description: "x",
      path: "data/skills/foo/SKILL.md",
      source: "user",
      body: "hi",
    });

    render(<SkillView name="foo" onBack={vi.fn()} />);

    await waitFor(() =>
      expect(screen.getByText(/Read-only/i)).toBeInTheDocument(),
    );

    expect(
      screen.queryByRole("button", { name: /save/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /delete/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^edit$/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("shows error state when fetch fails", async () => {
    fetchSkillMock.mockRejectedValueOnce(new Error("nope"));

    render(<SkillView name="foo" onBack={vi.fn()} />);

    await waitFor(() =>
      expect(screen.getByText(/Couldn't load skill/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/nope/)).toBeInTheDocument();
  });
});
