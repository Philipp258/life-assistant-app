import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { KnowledgeScreen } from "./KnowledgeScreen";
import {
  createFolder,
  createKnowledge,
  fetchTree,
  type Folder,
  type KnowledgeMeta,
  type Tree,
} from "./knowledgeApi";

const navigateMock = vi.hoisted(() => vi.fn());

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>(
    "react-router-dom",
  );
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock("./knowledgeApi", () => ({
  createFolder: vi.fn(),
  createKnowledge: vi.fn(),
  deleteFolder: vi.fn(),
  deleteKnowledge: vi.fn(),
  fetchTree: vi.fn(),
  searchKnowledge: vi.fn(),
  slugify: (title: string) =>
    title
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "untitled",
}));

const STAMP = "2026-05-28T12:00:00Z";

function meta(path: string, title: string): KnowledgeMeta {
  return { path, title, id: path, created: STAMP, updated: STAMP };
}

function folder(path: string, items: KnowledgeMeta[], folders: string[] = []): Folder {
  return { path, items, folders };
}

function tree(): Tree {
  return {
    folders: [
      folder("", [], ["work"]),
      folder("work", [meta("work/existing.md", "Existing")]),
    ],
  };
}

async function renderScreen() {
  vi.mocked(fetchTree).mockResolvedValue(tree());
  render(<KnowledgeScreen />);
  await screen.findByRole("heading", { name: "Knowledge" });
  await screen.findByRole("button", { name: /Expand work/ });
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
});

describe("KnowledgeScreen creation sheet", () => {
  it("creates a root knowledge note and navigates to it", async () => {
    vi.mocked(createKnowledge).mockResolvedValue({
      ...meta("my-note.md", "My Note"),
      body: "",
    });
    await renderScreen();

    await userEvent.click(screen.getByRole("button", { name: "New" }));
    await userEvent.type(screen.getByLabelText("Title"), "My Note");
    expect(screen.getByText("my-note.md")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => {
      expect(createKnowledge).toHaveBeenCalledWith("my-note.md", "", "My Note");
      expect(navigateMock).toHaveBeenCalledWith("/know/open/my-note.md");
    });
  });

  it("creates a note inside the expanded folder", async () => {
    vi.mocked(createKnowledge).mockResolvedValue({
      ...meta("work/project-plan.md", "Project Plan"),
      body: "",
    });
    await renderScreen();

    await userEvent.click(screen.getByRole("button", { name: /Expand work/ }));
    await userEvent.click(screen.getByRole("button", { name: "Knowledge" }));
    await userEvent.type(screen.getByLabelText("Title"), "Project Plan");
    expect(screen.getByText("work/project-plan.md")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => {
      expect(createKnowledge).toHaveBeenCalledWith(
        "work/project-plan.md",
        "",
        "Project Plan",
      );
      expect(navigateMock).toHaveBeenCalledWith("/know/open/work/project-plan.md");
    });
  });

  it("creates a folder inside the expanded folder", async () => {
    vi.mocked(createFolder).mockResolvedValue({ path: "work/ideas" });
    await renderScreen();

    await userEvent.click(screen.getByRole("button", { name: /Expand work/ }));
    await userEvent.click(screen.getByRole("button", { name: "Folder" }));
    await userEvent.type(screen.getByLabelText("Folder name"), "Ideas");
    expect(screen.getByText("work/ideas")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => {
      expect(createFolder).toHaveBeenCalledWith("work/ideas");
      expect(navigateMock).not.toHaveBeenCalled();
    });
  });

  it("keeps the sheet open and shows create errors inline", async () => {
    vi.mocked(createKnowledge).mockRejectedValue(new Error("already exists"));
    await renderScreen();

    await userEvent.click(screen.getByRole("button", { name: "New" }));
    await userEvent.type(screen.getByLabelText("Title"), "Duplicate");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText("already exists")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "New knowledge" })).toBeInTheDocument();
    expect(navigateMock).not.toHaveBeenCalled();
  });
});
