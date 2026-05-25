import type { Meta, StoryObj } from "@storybook/react-vite";
import { FileText, FolderClosed } from "lucide-react";
import { Fragment, useMemo, useState } from "react";

import { Header } from "@/shell/Header";

import { KnowledgeSearchInput } from "./KnowledgeSearchInput";

/**
 * Storybook prototypes for Knowledge search results.
 *
 * Decisions already locked in:
 *   - No index, no FTS, no semantic search. Plain substring match.
 *   - Content IS searched (document bodies), not just titles/paths.
 *   - Search runs on **Enter**, not on every keystroke.
 *   - Title is weighted heavier than path, path heavier than body.
 *
 * What's still open — and the only thing these stories exist to decide —
 * is how the matching documents are presented. Pick a variant; that one
 * gets wired into KnowledgeScreen and the backend snippet/highlight shape
 * is built to match it.
 *
 * Variants:
 *   - A: Ranked list, heavy title. Flat, title-first, one-line snippet.
 *   - B: Result cards. Roomier, folder chip, two-line snippet, date.
 *   - C: Compact rows. Minimal departure from today's KnowledgeRow.
 *        **Shipped** — the real screen mode-swaps to this (see
 *        KnowledgeSearchResults.tsx); A/B/D stay here as kept prototypes.
 *   - D: Grouped by where it matched ("In titles" / "In content").
 *        Makes the title weighting explicit instead of just implied.
 *
 * The mock `search()` below is the reference scoring implementation — the
 * backend endpoint mirrors it 1:1.
 */

// ---------------------------------------------------------------------------
// Mock knowledge base
// ---------------------------------------------------------------------------

type Doc = { path: string; title: string; updated: string; body: string };

const DOCS: Doc[] = [
  {
    path: "interests/bikes.md",
    title: "Bikes",
    updated: "2026-05-10T09:00:00Z",
    body: "Steel-frame gravel bikes are my favourite. Saving up for a Tumbleweed. Hate carbon for touring — too fragile on rough roads.",
  },
  {
    path: "interests/coffee.md",
    title: "Coffee setup",
    updated: "2026-05-12T18:30:00Z",
    body: "Niche Zero grinder, Gaggia Classic. Light roasts, 1:2.5 ratio, 93°C. Beans from Five Elephant.",
  },
  {
    path: "people/anna.md",
    title: "Anna",
    updated: "2026-05-14T11:00:00Z",
    body: "Sister. Birthday March 3. Allergic to peanuts. Lives in Lisbon now, works in product design. Loves gravel cycling too.",
  },
  {
    path: "people/dr-mertens.md",
    title: "Dr. Mertens (dentist)",
    updated: "2026-04-28T08:00:00Z",
    body: "Dentist near the office. Books out 6 weeks ahead. Recommended a night guard for grinding.",
  },
  {
    path: "trips/lisbon.md",
    title: "Lisbon trip",
    updated: "2026-05-13T20:00:00Z",
    body: "Visiting Anna in summer. Want to rent a gravel bike for a day along the coast. Pastéis de Belém non-negotiable.",
  },
  {
    path: "trips/japan-2027.md",
    title: "Japan 2027",
    updated: "2026-05-01T07:00:00Z",
    body: "Spring for cherry blossom. Tokyo, Kyoto, maybe a cycling leg on Shimanami Kaido. JR Pass maths still unclear.",
  },
  {
    path: "finance/taxes.md",
    title: "Taxes",
    updated: "2026-05-09T15:00:00Z",
    body: "Quarterly estimate due April 15. Accountant is Maria. Keep gravel-bike receipt — not deductible, just tracking spend.",
  },
  {
    path: "finance/subscriptions.md",
    title: "Subscriptions",
    updated: "2026-05-11T12:00:00Z",
    body: "Spotify, iCloud 2TB, gym (cancel — unused since Feb), newspaper. Review every quarter.",
  },
  {
    path: "recipes.md",
    title: "Recipes worth repeating",
    updated: "2026-05-08T19:00:00Z",
    body: "Anna's lentil soup. The 4-ingredient pasta. Overnight oats ratio 1:1:1. Coffee tiramisu for birthdays.",
  },
  {
    path: "ideas.md",
    title: "Random ideas",
    updated: "2026-05-15T22:00:00Z",
    body: "App that nags about subscriptions. A gravel route log. Birthday-gift tracker for Anna and the dentist (joke).",
  },
];

// ---------------------------------------------------------------------------
// Reference scoring — backend mirrors this exactly
// ---------------------------------------------------------------------------

type MatchField = "title" | "path" | "body";

type Hit = {
  path: string;
  title: string;
  updated: string;
  snippet: string | null;
  matchedIn: MatchField[];
  score: number;
};

const TITLE_W = 6;
const PATH_W = 3;
const BODY_W = 1;
const TITLE_PREFIX_BONUS = 4;
const SNIPPET_RADIUS = 70;

function tokenize(query: string): string[] {
  return query
    .toLowerCase()
    .split(/\s+/)
    .map((t) => t.trim())
    .filter(Boolean);
}

function makeSnippet(body: string, tokens: string[]): string | null {
  const lower = body.toLowerCase();
  let at = -1;
  for (const t of tokens) {
    const i = lower.indexOf(t);
    if (i !== -1 && (at === -1 || i < at)) at = i;
  }
  if (at === -1) return null;
  const start = Math.max(0, at - SNIPPET_RADIUS);
  const end = Math.min(body.length, at + SNIPPET_RADIUS);
  return (
    (start > 0 ? "…" : "") +
    body.slice(start, end).trim() +
    (end < body.length ? "…" : "")
  );
}

function search(query: string): Hit[] {
  const tokens = tokenize(query);
  if (tokens.length === 0) return [];

  const hits: Hit[] = [];
  for (const doc of DOCS) {
    const title = doc.title.toLowerCase();
    const path = doc.path.toLowerCase();
    const body = doc.body.toLowerCase();

    // AND: every token must appear somewhere in this doc.
    const everyTokenMatches = tokens.every(
      (t) => title.includes(t) || path.includes(t) || body.includes(t),
    );
    if (!everyTokenMatches) continue;

    let score = 0;
    const fields = new Set<MatchField>();
    for (const t of tokens) {
      if (title.includes(t)) {
        score += TITLE_W;
        fields.add("title");
      }
      if (path.includes(t)) {
        score += PATH_W;
        fields.add("path");
      }
      if (body.includes(t)) {
        score += BODY_W;
        fields.add("body");
      }
    }
    if (title.startsWith(tokens[0])) score += TITLE_PREFIX_BONUS;

    hits.push({
      path: doc.path,
      title: doc.title,
      updated: doc.updated,
      snippet: fields.has("body") ? makeSnippet(doc.body, tokens) : null,
      matchedIn: (["title", "path", "body"] as const).filter((f) =>
        fields.has(f),
      ),
      score,
    });
  }

  return hits.sort(
    (a, b) =>
      b.score - a.score ||
      b.updated.localeCompare(a.updated) ||
      a.title.localeCompare(b.title),
  );
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

/** Bold the matched tokens inside a string. */
function highlight(text: string, query: string) {
  const tokens = tokenize(query);
  if (tokens.length === 0) return text;
  const escaped = tokens.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const re = new RegExp(`(${escaped.join("|")})`, "gi");
  return text.split(re).map((part, i) =>
    escaped.some((e) => new RegExp(`^${e}$`, "i").test(part)) ? (
      <span key={i} className="font-semibold text-life-accent">
        {part}
      </span>
    ) : (
      <Fragment key={i}>{part}</Fragment>
    ),
  );
}

function folderOf(path: string): string {
  const i = path.lastIndexOf("/");
  return i === -1 ? "/" : path.slice(0, i);
}

/** Mini Knowledge-screen shell reused by every variant. */
function Frame({
  query,
  onQuery,
  children,
}: {
  query: string;
  onQuery: (q: string) => void;
  children: React.ReactNode;
}) {
  const [draft, setDraft] = useState(query);
  return (
    <div className="mx-auto flex h-[640px] w-full max-w-md flex-col overflow-hidden rounded-2xl border border-life-line bg-life-bg">
      <Header title="Knowledge" subtitle="KNOWLEDGE" />
      <div className="px-5 pb-2 pt-1">
        <KnowledgeSearchInput
          value={draft}
          onChange={setDraft}
          onSubmit={onQuery}
        />
        <div className="mt-1 px-1 text-[10px] text-life-ink-3">
          Press Enter to search titles and contents.
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-5 pb-6">{children}</div>
    </div>
  );
}

function IdleOrEmpty({ query }: { query: string }) {
  if (query.trim() === "") {
    return (
      <div className="py-10 text-center text-sm text-life-ink-3">
        Empty box → the normal folder tree shows here. Type a query and press
        Enter.
      </div>
    );
  }
  return (
    <div className="py-10 text-center text-sm text-life-ink-3">
      Nothing matches “{query.trim()}”.
    </div>
  );
}

/** Wraps a variant renderer with the query state + Frame. */
function useSearchStory() {
  const [query, setQuery] = useState("gravel");
  const hits = useMemo(() => search(query), [query]);
  return { query, setQuery, hits };
}

// ---------------------------------------------------------------------------
// Variant A — Ranked list, heavy title
// ---------------------------------------------------------------------------

export const A_RankedList_HeavyTitle: Story = {
  render: () => {
    const { query, setQuery, hits } = useSearchStory();
    return (
      <Frame query={query} onQuery={setQuery}>
        {hits.length === 0 ? (
          <IdleOrEmpty query={query} />
        ) : (
          <div className="flex flex-col">
            {hits.map((h, i) => (
              <button
                key={h.path}
                type="button"
                className={`flex flex-col gap-0.5 py-3 text-left ${
                  i > 0 ? "border-t border-life-line" : ""
                }`}
              >
                <div className="flex items-baseline gap-2">
                  <span className="text-[15px] font-semibold leading-tight text-life-ink">
                    {highlight(h.title, query)}
                  </span>
                  <span className="text-[10px] text-life-ink-3">
                    {folderOf(h.path)}
                  </span>
                </div>
                {h.snippet ? (
                  <span className="line-clamp-1 text-[12px] text-life-ink-2">
                    {highlight(h.snippet, query)}
                  </span>
                ) : (
                  <span className="text-[11px] italic text-life-ink-3">
                    matched in {h.matchedIn.join(" + ")}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </Frame>
    );
  },
};

// ---------------------------------------------------------------------------
// Variant B — Result cards
// ---------------------------------------------------------------------------

export const B_ResultCards: Story = {
  render: () => {
    const { query, setQuery, hits } = useSearchStory();
    return (
      <Frame query={query} onQuery={setQuery}>
        {hits.length === 0 ? (
          <IdleOrEmpty query={query} />
        ) : (
          <div className="flex flex-col gap-2 py-1">
            {hits.map((h) => (
              <button
                key={h.path}
                type="button"
                className="flex flex-col gap-1.5 rounded-2xl border border-life-line bg-life-card px-4 py-3 text-left"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[15px] font-semibold leading-tight text-life-ink">
                    {highlight(h.title, query)}
                  </span>
                  <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-life-bg px-2 py-0.5 text-[10px] text-life-ink-3">
                    <FolderClosed className="h-3 w-3" />
                    {folderOf(h.path)}
                  </span>
                </div>
                {h.snippet ? (
                  <span className="line-clamp-2 text-[12px] text-life-ink-2">
                    {highlight(h.snippet, query)}
                  </span>
                ) : (
                  <span className="text-[11px] italic text-life-ink-3">
                    matched in {h.matchedIn.join(" + ")}
                  </span>
                )}
                <span className="text-[10px] text-life-ink-3">
                  updated {h.updated.slice(0, 10)}
                </span>
              </button>
            ))}
          </div>
        )}
      </Frame>
    );
  },
};

// ---------------------------------------------------------------------------
// Variant C — Compact rows (closest to today's KnowledgeRow)
// ---------------------------------------------------------------------------

export const C_CompactRows: Story = {
  render: () => {
    const { query, setQuery, hits } = useSearchStory();
    return (
      <Frame query={query} onQuery={setQuery}>
        {hits.length === 0 ? (
          <IdleOrEmpty query={query} />
        ) : (
          <div className="mt-1 rounded-2xl border border-life-line bg-life-card px-3.5 py-1">
            {hits.map((h, i) => (
              <button
                key={h.path}
                type="button"
                className={`flex w-full items-center gap-2.5 px-1 py-2.5 text-left ${
                  i > 0 ? "border-t border-life-line" : ""
                }`}
              >
                <span className="text-life-ink-3">
                  <FileText className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13px] font-medium text-life-ink">
                    {highlight(h.title, query)}
                  </div>
                  <div className="truncate text-[10px] text-life-ink-3">
                    {h.snippet
                      ? highlight(h.snippet, query)
                      : h.path}
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
      </Frame>
    );
  },
};

// ---------------------------------------------------------------------------
// Variant D — Grouped by where it matched
// ---------------------------------------------------------------------------

export const D_GroupedByMatch: Story = {
  render: () => {
    const { query, setQuery, hits } = useSearchStory();
    const inTitle = hits.filter((h) => h.matchedIn.includes("title"));
    const inContentOnly = hits.filter((h) => !h.matchedIn.includes("title"));

    const Section = ({ label, rows }: { label: string; rows: Hit[] }) =>
      rows.length === 0 ? null : (
        <div className="mb-4">
          <div className="mb-1 px-1 text-[10px] font-semibold uppercase tracking-wide text-life-ink-3">
            {label}
          </div>
          <div className="flex flex-col">
            {rows.map((h, i) => (
              <button
                key={h.path}
                type="button"
                className={`flex flex-col gap-0.5 py-2.5 text-left ${
                  i > 0 ? "border-t border-life-line" : ""
                }`}
              >
                <div className="flex items-baseline gap-2">
                  <span className="text-[14px] font-semibold text-life-ink">
                    {highlight(h.title, query)}
                  </span>
                  <span className="text-[10px] text-life-ink-3">
                    {folderOf(h.path)}
                  </span>
                </div>
                {h.snippet && (
                  <span className="line-clamp-1 text-[12px] text-life-ink-2">
                    {highlight(h.snippet, query)}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>
      );

    return (
      <Frame query={query} onQuery={setQuery}>
        {hits.length === 0 ? (
          <IdleOrEmpty query={query} />
        ) : (
          <div className="pt-2">
            <Section label="In titles" rows={inTitle} />
            <Section label="In content" rows={inContentOnly} />
          </div>
        )}
      </Frame>
    );
  },
};

// ---------------------------------------------------------------------------
// States
// ---------------------------------------------------------------------------

/** What the screen looks like before any search (empty box → tree). */
export const State_Idle: Story = {
  render: () => {
    const [query, setQuery] = useState("");
    return (
      <Frame query={query} onQuery={setQuery}>
        <IdleOrEmpty query={query} />
      </Frame>
    );
  },
};

/** No document matches the query. */
export const State_NoResults: Story = {
  render: () => {
    const [query, setQuery] = useState("xylophone");
    return (
      <Frame query={query} onQuery={setQuery}>
        <IdleOrEmpty query={query} />
      </Frame>
    );
  },
};

/** Just the input chrome, for tweaking without the rest of the screen. */
export const InputOnly: Story = {
  render: () => {
    const [v, setV] = useState("");
    return (
      <div className="w-[340px] p-4">
        <KnowledgeSearchInput
          value={v}
          onChange={setV}
          onSubmit={() => undefined}
        />
      </div>
    );
  },
};

const meta = {
  title: "Knowledge/KnowledgeSearch",
  parameters: {
    layout: "centered",
    docs: {
      description: {
        component:
          "Knowledge search result-UI prototypes. Locked: no index, content is searched, runs on Enter, title weighted heaviest. **Shipped: C — Compact rows** (KnowledgeRow-style flat ranked list; the real screen mode-swaps to it). A/B/D remain as kept prototypes. Try editing the box and pressing Enter (default query: “gravel”; try “anna”, “coffee 1:2.5”, “interests”).",
      },
    },
  },
} satisfies Meta;

export default meta;
type Story = StoryObj<typeof meta>;
