import { memo } from "react";
import { useNavigate } from "react-router-dom";
import { LoaderIcon } from "lucide-react";
import type { ToolCallMessagePartComponent } from "@assistant-ui/react";

import { ToolFallback } from "@/components/assistant-ui/tool-fallback";
import { knowledgeRouteForPath } from "@/lib/markdownLinks";
import { cn } from "@/lib/utils";
import { IconCaret, IconDoc } from "@/shell/icons";

type SaveKnowledgeArgs = {
  path?: string;
  body?: string;
  title?: string | null;
};

type SaveKnowledgeResult = {
  ok: true;
  path: string;
  title: string;
  id: string;
  created: string;
  updated: string;
};

type Variant = "created" | "updated";

const VARIANT_COPY: Record<Variant, { running: string; header: string }> = {
  created: { running: "Saving knowledge", header: "Knowledge created" },
  updated: { running: "Updating knowledge", header: "Knowledge updated" },
};

function isSaveKnowledgeResult(value: unknown): value is SaveKnowledgeResult {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return v.ok === true && typeof v.path === "string" && typeof v.title === "string";
}

function makeCard(variant: Variant) {
  const copy = VARIANT_COPY[variant];
  const Card: ToolCallMessagePartComponent<SaveKnowledgeArgs, SaveKnowledgeResult | unknown> = (
    props,
  ) => {
    const { status, result, args } = props;
    const navigate = useNavigate();

    if (status?.type === "running") {
      const label = args?.title?.trim() || args?.path;
      return (
        <div
          data-slot="knowledge-saved-card-running"
          className="flex w-full items-center gap-2 rounded-2xl border border-life-line bg-life-card px-4 py-3 text-sm text-life-ink-3"
        >
          <LoaderIcon className="size-4 animate-spin text-life-accent" />
          <span>
            {copy.running}
            {label ? (
              <>
                : <span className="text-life-ink-2">{label}</span>
              </>
            ) : null}
            …
          </span>
        </div>
      );
    }

    if (status?.type === "incomplete" || !isSaveKnowledgeResult(result)) {
      return <ToolFallback {...props} />;
    }

    const open = () => navigate(knowledgeRouteForPath(result.path) ?? "/know");

    return (
      <button
        type="button"
        onClick={open}
        className={cn(
          "group/knowledge-card flex w-full items-start gap-3 rounded-2xl border border-life-line bg-life-card p-[14px] text-left transition-colors",
          "hover:border-life-accent/60 hover:bg-life-accent-soft/40",
        )}
        aria-label={`Open knowledge: ${result.title}`}
      >
        <div className="flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-[10px] bg-life-accent-soft text-life-accent">
          <IconDoc />
        </div>

        <div className="min-w-0 flex-1">
          <div className="text-[10px] font-bold uppercase tracking-[0.6px] text-life-accent">
            {copy.header}
          </div>
          <div className="mt-0.5 text-[15px] leading-tight font-medium text-life-ink">
            {result.title}
          </div>
          <div className="mt-1 truncate text-[12px] text-life-ink-3">
            {result.path}
          </div>
        </div>

        <span className="mt-1 text-life-ink-3 transition-transform group-hover/knowledge-card:translate-x-0.5">
          <IconCaret />
        </span>
      </button>
    );
  };
  return memo(Card) as ToolCallMessagePartComponent<
    SaveKnowledgeArgs,
    SaveKnowledgeResult | unknown
  >;
}

export const KnowledgeCreatedCard = makeCard("created");
export const KnowledgeUpdatedCard = makeCard("updated");
