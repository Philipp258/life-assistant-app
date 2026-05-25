import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { FolderTreeView } from "./FolderTreeView";
import type { Folder, KnowledgeMeta, Tree } from "./knowledgeApi";

beforeAll(() => {
  if (typeof window.localStorage?.setItem !== "function") {
    let store: Record<string, string> = {};
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        get length() {
          return Object.keys(store).length;
        },
        clear() {
          store = {};
        },
        getItem(key: string) {
          return Object.prototype.hasOwnProperty.call(store, key)
            ? store[key]
            : null;
        },
        setItem(key: string, value: string) {
          store[key] = String(value);
        },
        removeItem(key: string) {
          delete store[key];
        },
        key(i: number) {
          return Object.keys(store)[i] ?? null;
        },
      },
    });
  }
});

const STAMP = "2026-04-30T12:00:00Z";

function meta(folderPath: string, slug: string, title: string): KnowledgeMeta {
  const path = folderPath ? `${folderPath}/${slug}.md` : `${slug}.md`;
  return { path, title, id: path, created: STAMP, updated: STAMP };
}

function folder(
  path: string,
  items: KnowledgeMeta[],
  folders: string[] = [],
): Folder {
  return { path, items, folders };
}

function makeTree(): Tree {
  return {
    folders: [
      folder("", [meta("", "loose-note", "Loose note")], [
        "work",
        "personal",
      ]),
      folder("work", [meta("work", "okrs", "OKRs"), meta("work", "roadmap", "Roadmap")]),
      folder(
        "personal",
        [meta("personal", "birthdays", "Birthdays")],
        ["personal/finance"],
      ),
      folder("personal/finance", [meta("personal/finance", "budget", "Budget")]),
    ],
  };
}

function emptyTree(): Tree {
  return { folders: [folder("", [])] };
}

function makeHandlers() {
  return {
    onOpen: vi.fn(),
    onCreate: vi.fn(),
    onCreateFolder: vi.fn(),
    onDeleteFolder: vi.fn(),
    onDelete: vi.fn(),
  };
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  window.localStorage.clear();
});

describe("FolderTreeView", () => {
  it("defaults to all folders collapsed (overview-first)", () => {
    const handlers = makeHandlers();
    render(<FolderTreeView tree={makeTree()} {...handlers} />);

    expect(screen.getByRole("button", { name: /Expand work/ })).toBeInTheDocument();
    expect(screen.queryByText("OKRs")).not.toBeInTheDocument();
    expect(screen.queryByText("Roadmap")).not.toBeInTheDocument();
  });

  it("clicking a folder expands its items; clicking again collapses", async () => {
    const handlers = makeHandlers();
    render(<FolderTreeView tree={makeTree()} {...handlers} />);

    await userEvent.click(screen.getByRole("button", { name: /Expand work/ }));
    expect(screen.getByText("OKRs")).toBeInTheDocument();
    expect(screen.getByText("Roadmap")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Collapse work/ }));
    expect(screen.queryByText("OKRs")).not.toBeInTheDocument();
  });

  it("nested subfolders are reachable by expanding parent then child", async () => {
    const handlers = makeHandlers();
    render(<FolderTreeView tree={makeTree()} {...handlers} />);

    await userEvent.click(
      screen.getByRole("button", { name: /Expand personal/ }),
    );
    expect(screen.getByText("Birthdays")).toBeInTheDocument();
    expect(screen.queryByText("Budget")).not.toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: /Expand finance/ }),
    );
    expect(screen.getByText("Budget")).toBeInTheDocument();
  });

  it("expand all opens every folder; collapse all closes them", async () => {
    const handlers = makeHandlers();
    render(<FolderTreeView tree={makeTree()} {...handlers} />);

    expect(screen.queryByText("OKRs")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Expand all" }));
    expect(screen.getByText("OKRs")).toBeInTheDocument();
    expect(screen.getByText("Birthdays")).toBeInTheDocument();
    expect(screen.getByText("Budget")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Collapse all" }));
    expect(screen.queryByText("OKRs")).not.toBeInTheDocument();
    expect(screen.queryByText("Budget")).not.toBeInTheDocument();
  });

  it("persists open state across remounts via localStorage", async () => {
    const handlers = makeHandlers();
    const { unmount } = render(
      <FolderTreeView tree={makeTree()} {...handlers} />,
    );

    await userEvent.click(screen.getByRole("button", { name: /Expand work/ }));
    expect(screen.getByText("OKRs")).toBeInTheDocument();

    unmount();
    render(<FolderTreeView tree={makeTree()} {...handlers} />);
    expect(screen.getByText("OKRs")).toBeInTheDocument();
  });

  it("clicking an item invokes onOpen with its path", async () => {
    const handlers = makeHandlers();
    render(<FolderTreeView tree={makeTree()} {...handlers} />);

    await userEvent.click(screen.getByRole("button", { name: /Expand work/ }));
    await userEvent.click(screen.getByText("OKRs"));

    expect(handlers.onOpen).toHaveBeenCalledWith("work/okrs.md");
  });

  it("create knowledge / folder buttons fire with the parent path", async () => {
    const handlers = makeHandlers();
    render(<FolderTreeView tree={makeTree()} {...handlers} />);

    await userEvent.click(screen.getByRole("button", { name: /Expand work/ }));
    const knowledgeBtn = screen
      .getAllByRole("button", { name: /Knowledge/ })
      .find((el) => el.textContent?.trim() === "Knowledge");
    const folderBtn = screen
      .getAllByRole("button", { name: /Folder/ })
      .find((el) => el.textContent?.trim() === "Folder");

    await userEvent.click(knowledgeBtn!);
    expect(handlers.onCreate).toHaveBeenCalledWith("work");

    await userEvent.click(folderBtn!);
    expect(handlers.onCreateFolder).toHaveBeenCalledWith("work");
  });

  it("delete-folder button fires onDeleteFolder for non-root folders only", async () => {
    const handlers = makeHandlers();
    render(<FolderTreeView tree={makeTree()} {...handlers} />);

    await userEvent.click(
      screen.getByRole("button", { name: /Delete folder work/ }),
    );
    expect(handlers.onDeleteFolder).toHaveBeenCalledWith("work");

    expect(
      screen.queryByRole("button", { name: /Delete folder Loose/ }),
    ).not.toBeInTheDocument();
  });

  it("delete-item button fires onDelete with item path", async () => {
    const handlers = makeHandlers();
    render(<FolderTreeView tree={makeTree()} {...handlers} />);

    await userEvent.click(screen.getByRole("button", { name: /Expand work/ }));
    const deleteBtns = screen.getAllByRole("button", { name: "Delete" });
    await userEvent.click(deleteBtns[0]);
    expect(handlers.onDelete).toHaveBeenCalledWith("work/okrs.md");
  });

  it("renders empty state when there are no folders or items", () => {
    const handlers = makeHandlers();
    render(<FolderTreeView tree={emptyTree()} {...handlers} />);
    expect(screen.getByText(/Nothing here yet/)).toBeInTheDocument();
  });

  it("renders Loose root only when there are loose items", () => {
    const handlers = makeHandlers();
    render(<FolderTreeView tree={makeTree()} {...handlers} />);
    expect(screen.getByRole("button", { name: /Expand Loose/ })).toBeInTheDocument();
  });

  it("recursive item count includes subfolder items in the summary", () => {
    const handlers = makeHandlers();
    render(<FolderTreeView tree={makeTree()} {...handlers} />);

    const personalBtn = screen.getByRole("button", { name: /Expand personal/ });
    expect(personalBtn.textContent).toMatch(/2 items/);
    expect(personalBtn.textContent).toMatch(/1 folder/);
  });
});
