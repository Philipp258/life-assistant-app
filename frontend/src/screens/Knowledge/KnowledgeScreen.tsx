import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
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

type CreateDraft =
  | { kind: "note"; folderPath: string }
  | { kind: "folder"; folderPath: string }
  | null;

export function KnowledgeScreen() {
  const navigate = useNavigate();
  const [tree, setTree] = useState<Tree | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [createDraft, setCreateDraft] = useState<CreateDraft>(null);

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

  const handleCreate = useCallback((folderPath: string) => {
    setCreateDraft({ kind: "note", folderPath });
  }, []);

  const handleCreateFolder = useCallback((folderPath: string) => {
    setCreateDraft({ kind: "folder", folderPath });
  }, []);

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

      <CreateKnowledgeSheet
        draft={createDraft}
        onClose={() => setCreateDraft(null)}
        onCreated={async (path) => {
          await refresh();
          setCreateDraft(null);
          if (path) navigate(knowledgePath(path));
        }}
      />
    </div>
  );
}

function CreateKnowledgeSheet({
  draft,
  onClose,
  onCreated,
}: {
  draft: CreateDraft;
  onClose: () => void;
  onCreated: (path?: string) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!draft) return;
    setName("");
    setError(null);
    setSaving(false);
  }, [draft]);

  const slug = useMemo(() => slugify(name), [name]);
  const path = draft
    ? (draft.folderPath ? `${draft.folderPath}/` : "") +
      (draft.kind === "note" ? `${slug}.md` : slug)
    : "";
  const targetFolder = draft?.folderPath || "Knowledge root";
  const title = draft?.kind === "folder" ? "New folder" : "New knowledge";
  const label = draft?.kind === "folder" ? "Folder name" : "Title";

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!draft || saving || !name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      if (draft.kind === "note") {
        await createKnowledge(path, "", name.trim());
        await onCreated(path);
      } else {
        await createFolder(path);
        await onCreated();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Sheet open={draft !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent
        side="bottom"
        className="h-auto max-h-[90dvh] overflow-y-auto rounded-t-3xl border-life-line bg-life-bg p-0 text-life-ink sm:max-w-none"
        showCloseButton={false}
      >
        <form onSubmit={submit} className="flex flex-col gap-4 px-5 pt-3 pb-10">
          <div className="mx-auto my-1 h-1 w-10 rounded bg-life-line" />
          <SheetHeader className="gap-1 p-0 text-left">
            <SheetDescription className="text-[10px] font-bold tracking-[0.6px] text-life-accent uppercase">
              {targetFolder}
            </SheetDescription>
            <SheetTitle className="font-serif text-[28px] leading-[1.1] font-normal text-life-ink">
              {title}
            </SheetTitle>
          </SheetHeader>

          <div className="flex flex-col gap-2">
            <Label htmlFor="knowledge-create-name">{label}</Label>
            <Input
              id="knowledge-create-name"
              autoFocus
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={draft?.kind === "folder" ? "Project notes" : "Project brief"}
              disabled={saving}
            />
          </div>

          <div className="rounded-md bg-life-surface-2 px-3 py-2 text-[11px] text-life-ink-3">
            <div className="font-medium text-life-ink-2">Path</div>
            <div className="mt-0.5 break-all font-mono">{path}</div>
          </div>

          {error ? <p className="text-sm text-red-500">{error}</p> : null}

          <div className="flex items-center justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={onClose}
              disabled={saving}
              className="rounded-full"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={saving || !name.trim()}
              className="rounded-full"
            >
              {saving ? "Creating..." : "Create"}
            </Button>
          </div>
        </form>
      </SheetContent>
    </Sheet>
  );
}
