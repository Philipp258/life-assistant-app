import { useCallback, useEffect, useMemo, useState } from "react";

import {
  IconCaret,
  IconClose,
  IconDoc,
  IconFolder,
  IconPlus,
  IconTrash,
} from "@/shell/icons";
import { useIdentity } from "@/shell/identity";
import { cn } from "@/lib/utils";

import type { Folder, KnowledgeMeta, Tree } from "./knowledgeApi";

const STORAGE_KEY = "lifeAssistant.knowledge.openFolders";

type FolderTreeViewProps = {
  tree: Tree;
  onOpen: (path: string) => void;
  onCreate: (folderPath: string) => void;
  onCreateFolder: (parentPath: string) => void;
  onDeleteFolder: (path: string) => void;
  onDelete: (path: string) => void;
};

type ChildIndex = {
  byPath: Map<string, Folder>;
  childrenOf: Map<string, Folder[]>;
};

function indexTree(tree: Tree): ChildIndex {
  const byPath = new Map<string, Folder>();
  for (const f of tree.folders) byPath.set(f.path, f);

  const childrenOf = new Map<string, Folder[]>();
  for (const f of tree.folders) {
    if (f.path === "") continue;
    const lastSlash = f.path.lastIndexOf("/");
    const parent = lastSlash === -1 ? "" : f.path.slice(0, lastSlash);
    const arr = childrenOf.get(parent) ?? [];
    arr.push(f);
    childrenOf.set(parent, arr);
  }
  for (const arr of childrenOf.values()) {
    arr.sort((a, b) => a.path.localeCompare(b.path));
  }
  return { byPath, childrenOf };
}

function folderName(path: string): string {
  if (path === "") return "Loose";
  const i = path.lastIndexOf("/");
  return i === -1 ? path : path.slice(i + 1);
}

function recursiveItemCount(
  index: ChildIndex,
  path: string,
): { items: number; folders: number } {
  const f = index.byPath.get(path);
  if (!f) return { items: 0, folders: 0 };
  let items = f.items.length;
  let folders = 0;
  const kids = index.childrenOf.get(path) ?? [];
  for (const child of kids) {
    folders += 1;
    const sub = recursiveItemCount(index, child.path);
    items += sub.items;
    folders += sub.folders;
  }
  return { items, folders };
}

function loadOpenPaths(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr)) return new Set();
    return new Set(arr.filter((x) => typeof x === "string"));
  } catch {
    return new Set();
  }
}

function saveOpenPaths(paths: Set<string>): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify(Array.from(paths)),
    );
  } catch {
    // ignore quota / disabled storage
  }
}

export function FolderTreeView({
  tree,
  onOpen,
  onCreate,
  onCreateFolder,
  onDeleteFolder,
  onDelete,
}: FolderTreeViewProps) {
  const { assistantName } = useIdentity();
  const index = useMemo(() => indexTree(tree), [tree]);
  const [openPaths, setOpenPaths] = useState<Set<string>>(loadOpenPaths);

  useEffect(() => {
    saveOpenPaths(openPaths);
  }, [openPaths]);

  const toggle = useCallback((path: string) => {
    setOpenPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const expandAll = useCallback(() => {
    setOpenPaths(new Set(tree.folders.map((f) => f.path)));
  }, [tree.folders]);

  const collapseAll = useCallback(() => {
    setOpenPaths(new Set());
  }, []);

  const root = index.byPath.get("");
  const topLevel = index.childrenOf.get("") ?? [];
  const showRootLoose = !!root && root.items.length > 0;

  const isEmpty =
    tree.folders.length <= 1 && (!root || root.items.length === 0);

  if (isEmpty) {
    return (
      <div className="mt-3 flex flex-col items-center gap-3 py-8 text-center text-sm text-life-ink-3">
        <div>
          Nothing here yet. Tell {assistantName} to remember things, or create one
          yourself.
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => onCreate("")}
            className="rounded-full bg-life-accent px-4 py-1.5 text-xs font-medium text-white"
          >
            + Knowledge
          </button>
          <button
            type="button"
            onClick={() => onCreateFolder("")}
            className="rounded-full border border-life-line bg-life-card px-4 py-1.5 text-xs font-medium text-life-ink-2"
          >
            + Folder
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between px-1">
        <div className="text-[11px] uppercase tracking-[0.6px] text-life-ink-3">
          {topLevel.length} {topLevel.length === 1 ? "folder" : "folders"}
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={expandAll}
            className="rounded-full border border-life-line bg-life-card px-3 py-1 text-[11px] font-medium text-life-ink-2 hover:bg-life-bg"
          >
            Expand all
          </button>
          <button
            type="button"
            onClick={collapseAll}
            className="rounded-full border border-life-line bg-life-card px-3 py-1 text-[11px] font-medium text-life-ink-2 hover:bg-life-bg"
          >
            Collapse all
          </button>
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        {showRootLoose && (
          <FolderNode
            path=""
            depth={0}
            index={index}
            openPaths={openPaths}
            toggle={toggle}
            onOpen={onOpen}
            onCreate={onCreate}
            onCreateFolder={onCreateFolder}
            onDeleteFolder={onDeleteFolder}
            onDelete={onDelete}
          />
        )}
        {topLevel.map((f) => (
          <FolderNode
            key={f.path}
            path={f.path}
            depth={0}
            index={index}
            openPaths={openPaths}
            toggle={toggle}
            onOpen={onOpen}
            onCreate={onCreate}
            onCreateFolder={onCreateFolder}
            onDeleteFolder={onDeleteFolder}
            onDelete={onDelete}
          />
        ))}
      </div>
    </div>
  );
}

type FolderNodeProps = {
  path: string;
  depth: number;
  index: ChildIndex;
  openPaths: Set<string>;
  toggle: (path: string) => void;
  onOpen: (path: string) => void;
  onCreate: (folderPath: string) => void;
  onCreateFolder: (parentPath: string) => void;
  onDeleteFolder: (path: string) => void;
  onDelete: (path: string) => void;
};

function FolderNode({
  path,
  depth,
  index,
  openPaths,
  toggle,
  onOpen,
  onCreate,
  onCreateFolder,
  onDeleteFolder,
  onDelete,
}: FolderNodeProps) {
  const folder = index.byPath.get(path);
  if (!folder) return null;

  const isRoot = path === "";
  const open = openPaths.has(path);
  const kids = isRoot ? [] : index.childrenOf.get(path) ?? [];
  const counts = recursiveItemCount(index, path);
  const indentPx = depth * 18;

  const summary =
    counts.folders > 0
      ? `${counts.items} items, ${counts.folders} ${counts.folders === 1 ? "folder" : "folders"}`
      : `${counts.items} ${counts.items === 1 ? "item" : "items"}`;

  return (
    <div className="flex flex-col">
      <div
        className="flex items-center rounded-2xl border border-life-line bg-life-card"
        style={{ marginLeft: indentPx }}
      >
        <button
          type="button"
          onClick={() => toggle(path)}
          aria-expanded={open}
          aria-label={`${open ? "Collapse" : "Expand"} ${folderName(path)}`}
          className="flex flex-1 items-center gap-2 py-2.5 pl-3 pr-2 text-left"
        >
          <span
            className={cn(
              "transition-transform text-life-ink-3",
              open ? "rotate-90" : "rotate-0",
            )}
          >
            <IconCaret />
          </span>
          <span className="text-life-accent">
            <IconFolder />
          </span>
          <span className="flex-1 truncate text-[14px] font-medium text-life-ink">
            {folderName(path)}
          </span>
          <span className="text-[11px] text-life-ink-3">{summary}</span>
        </button>
        {!isRoot && (
          <button
            type="button"
            onClick={() => onDeleteFolder(path)}
            aria-label={`Delete folder ${folderName(path)}`}
            className="mr-2 rounded p-1 text-life-ink-3 hover:bg-life-bg hover:text-red-500"
          >
            <IconTrash />
          </button>
        )}
      </div>

      {open && (
        <div
          className="mt-1 flex flex-col gap-1.5"
          style={{ marginLeft: indentPx + 18 }}
        >
          {kids.map((child) => (
            <FolderNode
              key={child.path}
              path={child.path}
              depth={depth + 1}
              index={index}
              openPaths={openPaths}
              toggle={toggle}
              onOpen={onOpen}
              onCreate={onCreate}
              onCreateFolder={onCreateFolder}
              onDeleteFolder={onDeleteFolder}
              onDelete={onDelete}
            />
          ))}
          <div className="rounded-2xl border border-life-line bg-life-card px-3.5 py-1">
            {folder.items.map((item, i) => (
              <KnowledgeRow
                key={item.path}
                item={item}
                first={i === 0}
                onOpen={() => onOpen(item.path)}
                onDelete={() => onDelete(item.path)}
              />
            ))}
            {folder.items.length === 0 && kids.length === 0 && (
              <div className="px-2 py-3 text-center text-xs text-life-ink-3">
                Empty.
              </div>
            )}
            <div className="mt-2 flex gap-2 border-t border-life-line pt-2">
              <button
                type="button"
                onClick={() => onCreate(path)}
                className="flex items-center gap-1 rounded-full border border-life-line bg-life-bg px-3 py-1 text-[11px] font-medium text-life-ink-2 hover:bg-life-card"
              >
                <IconPlus /> Knowledge
              </button>
              <button
                type="button"
                onClick={() => onCreateFolder(path)}
                className="flex items-center gap-1 rounded-full border border-life-line bg-life-bg px-3 py-1 text-[11px] font-medium text-life-ink-2 hover:bg-life-card"
              >
                <IconPlus /> Folder
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function KnowledgeRow({
  item,
  first,
  onOpen,
  onDelete,
}: {
  item: KnowledgeMeta;
  first: boolean;
  onOpen: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      className={cn(
        "flex items-center gap-2.5 px-1 py-2.5",
        !first && "border-t border-life-line",
      )}
    >
      <button
        type="button"
        onClick={onOpen}
        className="flex flex-1 items-center gap-2.5 text-left"
      >
        <span className="text-life-ink-3">
          <IconDoc />
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] text-life-ink">{item.title}</div>
          <div className="truncate text-[10px] text-life-ink-3">
            {item.path}
          </div>
        </div>
      </button>
      <button
        type="button"
        onClick={onDelete}
        aria-label="Delete"
        className="rounded p-1 text-life-ink-3 hover:bg-life-bg hover:text-red-500"
      >
        <IconClose />
      </button>
    </div>
  );
}
