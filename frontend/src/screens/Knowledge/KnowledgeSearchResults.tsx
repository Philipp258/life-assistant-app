import { Fragment, useMemo } from "react";

import { IconDoc } from "@/shell/icons";
import { cn } from "@/lib/utils";

import type { KnowledgeSearchHit } from "./knowledgeApi";

/** Bold the matched query tokens inside a string. */
function highlight(text: string, query: string) {
  const tokens = query
    .toLowerCase()
    .split(/\s+/)
    .map((t) => t.trim())
    .filter(Boolean);
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

type KnowledgeSearchResultsProps = {
  hits: KnowledgeSearchHit[];
  query: string;
  onOpen: (path: string) => void;
};

/** Flat, relevance-ranked result list. Visually it is the same row as the
 * folder tree's KnowledgeRow — search just flattens, ranks, and adds a
 * snippet, so browse and find share one language. */
export function KnowledgeSearchResults({
  hits,
  query,
  onOpen,
}: KnowledgeSearchResultsProps) {
  const trimmed = useMemo(() => query.trim(), [query]);

  if (hits.length === 0) {
    return (
      <div className="py-10 text-center text-sm text-life-ink-3">
        Nothing matches “{trimmed}”.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="px-1 text-[11px] uppercase tracking-[0.6px] text-life-ink-3">
        {hits.length} {hits.length === 1 ? "result" : "results"}
      </div>
      <div className="rounded-2xl border border-life-line bg-life-card px-3.5 py-1">
        {hits.map((h, i) => (
          <button
            key={h.path}
            type="button"
            onClick={() => onOpen(h.path)}
            className={cn(
              "flex w-full items-center gap-2.5 px-1 py-2.5 text-left",
              i > 0 && "border-t border-life-line",
            )}
          >
            <span className="shrink-0 text-life-ink-3">
              <IconDoc />
            </span>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13px] font-semibold text-life-ink">
                {highlight(h.title, query)}
              </div>
              <div className="truncate text-[10px] text-life-ink-3">
                {h.snippet ? highlight(h.snippet, query) : h.path}
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
