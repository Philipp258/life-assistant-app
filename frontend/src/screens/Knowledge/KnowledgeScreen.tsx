import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Header } from "@/shell/Header";
import { IconPlus } from "@/shell/icons";
import { knowledgeRouteForPath } from "@/lib/markdownLinks";

import { FolderTreeView } from "./FolderTreeView";
import { KnowledgeSearchInput } from "./KnowledgeSearchInput";
import { KnowledgeSearchResults } from "./KnowledgeSearchResults";
import {
  createFolder,
  createKnowledge,
  deleteFolder,
  deleteKnowledge,
  fetchTree,
  searchKnowledge,
  slugify,
  type KnowledgeSearchHit,
  type Tree,
} from "./knowledgeApi";

function knowledgePath(path: string): string {
  return knowledgeRouteForPath(path) ?? "/know";
}

export function KnowledgeScreen() {
  const navigate = useNavigate();
  const [tree, setTree] = useState<Tree | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Search is a separate mode: `results === null` → browse the folder tree;
  // non-null → show the flat ranked results for `activeQuery`. Clearing the
  // box (or submitting blank) returns to browse.
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<KnowledgeSearchHit[] | null>(null);
  const [activeQuery, setActiveQuery] = useState("");
  const [searching, setSearching] = useState(false);

  const runSearch = useCallback(async (q: string) => {
    const trimmed = q.trim();
    if (!trimmed) {
      setResults(null);
      setActiveQuery("");
      setError(null);
      return;
    }
    setSearching(true);
    try {
      setResults(await searchKnowledge(trimmed));
      setActiveQuery(trimmed);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSearching(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      setTree(await fetchTree());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleCreate = useCallback(
    async (folderPath: string) => {
      const title = window.prompt("Title?", "");
      if (!title || !title.trim()) return;
      const slug = slugify(title);
      const path = (folderPath ? `${folderPath}/` : "") + `${slug}.md`;
      try {
        await createKnowledge(path, "", title);
        await refresh();
        navigate(knowledgePath(path));
      } catch (e) {
        window.alert(e instanceof Error ? e.message : String(e));
      }
    },
    [refresh, navigate],
  );

  const handleCreateFolder = useCallback(
    async (parentPath: string) => {
      const name = window.prompt("New folder name?", "");
      if (!name || !name.trim()) return;
      const slug = slugify(name);
      const path = (parentPath ? `${parentPath}/` : "") + slug;
      try {
        await createFolder(path);
        await refresh();
      } catch (e) {
        window.alert(e instanceof Error ? e.message : String(e));
      }
    },
    [refresh],
  );

  const handleDeleteFolder = useCallback(
    async (folderPath: string) => {
      if (
        !window.confirm(
          `Delete folder "${folderPath}" and everything inside it?`,
        )
      )
        return;
      try {
        await deleteFolder(folderPath);
        await refresh();
      } catch (e) {
        window.alert(e instanceof Error ? e.message : String(e));
      }
    },
    [refresh],
  );

  const handleDelete = useCallback(
    async (path: string) => {
      if (!window.confirm(`Delete "${path}"?`)) return;
      try {
        await deleteKnowledge(path);
        await refresh();
      } catch (e) {
        window.alert(e instanceof Error ? e.message : String(e));
      }
    },
    [refresh],
  );

  return (
    <div className="flex h-full flex-col">
      <Header
        title="Knowledge"
        subtitle="KNOWLEDGE"
        right={
          <button
            type="button"
            onClick={() => handleCreate("")}
            className="flex items-center gap-1.5 rounded-full bg-life-accent px-3.5 py-2 text-[13px] font-medium text-white"
          >
            <IconPlus />
            New
          </button>
        }
      />

      <div className="px-5 pb-2 pt-1">
        <KnowledgeSearchInput
          value={query}
          onChange={setQuery}
          onSubmit={runSearch}
        />
      </div>

      <div className="flex-1 overflow-y-auto px-5 pb-6">
        {error && (
          <div className="py-6 text-center text-sm text-red-500">
            Couldn't load knowledge: {error}
          </div>
        )}

        {results !== null ? (
          searching ? (
            <div className="py-10 text-center text-sm text-life-ink-3">
              Searching…
            </div>
          ) : (
            <KnowledgeSearchResults
              hits={results}
              query={activeQuery}
              onOpen={(p) => navigate(knowledgePath(p))}
            />
          )
        ) : (
          <>
            {tree === null && !error && (
              <div className="py-10 text-center text-sm text-life-ink-3">
                Loading…
              </div>
            )}

            {tree && (
              <FolderTreeView
                tree={tree}
                onOpen={(p) => navigate(knowledgePath(p))}
                onCreate={handleCreate}
                onCreateFolder={handleCreateFolder}
                onDeleteFolder={handleDeleteFolder}
                onDelete={handleDelete}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}
