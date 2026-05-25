import { memo, useId, useState } from "react";
import { CheckIcon, LoaderIcon } from "lucide-react";
import type { ToolCallMessagePartComponent } from "@assistant-ui/react";
import { useAui, useAuiState } from "@assistant-ui/react";

import { ToolFallback } from "@/components/assistant-ui/tool-fallback";
import { MarkdownView } from "@/components/MarkdownView";
import { cn } from "@/lib/utils";

type AskUserChoiceArgs = {
  question?: string;
  options?: string[];
  allow_free_text?: boolean;
};

type AskUserChoiceResult = {
  ok: true;
  asked: string;
  options: string[];
  allow_free_text: boolean;
};

export type ChoiceCardViewProps = {
  question: string;
  options: string[];
  allowFreeText: boolean;
  alreadyAnswered?: boolean;
  selectedAnswer?: string | null;
  submitting?: boolean;
  onSubmit?: (text: string) => void;
  className?: string;
};

function isAskUserChoiceResult(value: unknown): value is AskUserChoiceResult {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    v.ok === true &&
    typeof v.asked === "string" &&
    Array.isArray(v.options)
  );
}

function textFromMessage(message: unknown): string {
  if (!message || typeof message !== "object") return "";
  const content = (message as { content?: unknown }).content;
  if (typeof content === "string") return content.trim();
  if (!Array.isArray(content)) return "";

  return content
    .map((part) => {
      if (!part || typeof part !== "object") return "";
      const p = part as { type?: unknown; text?: unknown };
      return p.type === "text" && typeof p.text === "string" ? p.text : "";
    })
    .join("")
    .trim();
}

const ChoiceCardImpl: ToolCallMessagePartComponent<
  AskUserChoiceArgs,
  AskUserChoiceResult | unknown
> = (props) => {
  const { status, args, result } = props;
  const aui = useAui();
  const messageId = useAuiState((s) => s.message.id);
  const selectedAnswer = useAuiState((s) => {
    const messages = s.thread.messages;
    const idx = messages.findIndex((m) => m.id === messageId);
    if (idx === -1) return undefined;

    const answer = messages.slice(idx + 1).find((m) => m.role === "user");
    if (!answer) return undefined;

    return textFromMessage(answer) || null;
  });
  const [submitting, setSubmitting] = useState(false);

  if (status?.type === "running") {
    return (
      <div
        data-slot="choice-card-running"
        className="flex w-full items-center gap-2 rounded-2xl border border-life-line bg-life-card px-4 py-3 text-sm text-life-ink-3"
      >
        <LoaderIcon className="size-4 animate-spin text-life-accent" />
        <span>Preparing question…</span>
      </div>
    );
  }

  // Prefer the recorded result (canonical) but fall back to the args while
  // streaming finishes.
  const question = isAskUserChoiceResult(result) ? result.asked : args?.question;
  const options =
    isAskUserChoiceResult(result) ? result.options : args?.options ?? [];
  const allowFreeText =
    isAskUserChoiceResult(result)
      ? result.allow_free_text
      : args?.allow_free_text ?? true;

  if (status?.type === "incomplete" || !question || options.length === 0) {
    return <ToolFallback {...props} />;
  }

  const send = (text: string) => {
    if (!text.trim() || submitting) return;
    setSubmitting(true);
    aui.thread().append(text);
  };

  return (
    <ChoiceCardView
      question={question}
      options={options}
      allowFreeText={allowFreeText}
      alreadyAnswered={selectedAnswer !== undefined}
      selectedAnswer={selectedAnswer ?? null}
      submitting={submitting}
      onSubmit={send}
    />
  );
};

export function ChoiceCardView({
  question,
  options,
  allowFreeText,
  alreadyAnswered = false,
  selectedAnswer = null,
  submitting = false,
  onSubmit,
  className,
}: ChoiceCardViewProps) {
  const [customDraft, setCustomDraft] = useState("");
  const [showCustom, setShowCustom] = useState(false);
  const customPanelId = useId();
  const normalizedSelectedAnswer = selectedAnswer?.trim() ?? "";
  const selectedOptionIndex = alreadyAnswered
    ? options.findIndex((option) => option.trim() === normalizedSelectedAnswer)
    : -1;
  const hasCustomAnswer =
    alreadyAnswered &&
    normalizedSelectedAnswer.length > 0 &&
    selectedOptionIndex === -1;

  const send = (text: string) => {
    if (!text.trim() || submitting || alreadyAnswered) return;
    onSubmit?.(text);
  };

  return (
    <div
      data-slot="choice-card"
      className={cn(
        "flex w-full flex-col gap-3 rounded-2xl border border-life-line bg-life-card p-[14px]",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="text-[10px] font-bold uppercase tracking-[0.6px] text-life-accent">
          Choice needed
        </div>
        <div className="shrink-0 rounded-full bg-life-bg px-2 py-0.5 text-[11px] text-life-ink-3">
          {options.length} {options.length === 1 ? "option" : "options"}
        </div>
      </div>

      <MarkdownView
        source={question}
        className={cn(
          "text-[14px] leading-relaxed text-life-ink",
          "[&_.aui-md-h1]:text-[15px] [&_.aui-md-h2]:text-[14px]",
          "[&_.aui-md-p]:my-2 [&_.aui-md-ul]:my-1.5 [&_.aui-md-ol]:my-1.5",
          "[&_.aui-md-li]:leading-relaxed [&_.aui-md-pre]:my-2",
        )}
      />

      <div className="flex flex-col gap-1.5 border-t border-life-line pt-3">
        {options.map((option, i) => {
          const selected = i === selectedOptionIndex;

          return (
            <button
              key={i}
              type="button"
              disabled={submitting || alreadyAnswered}
              aria-pressed={alreadyAnswered ? selected : undefined}
              onClick={() => send(option)}
              className={cn(
                "flex w-full items-start gap-2 rounded-xl border px-3 py-2.5 text-left text-[13.5px] font-medium leading-snug transition-colors",
                selected
                  ? "border-life-accent bg-life-accent-soft text-life-ink shadow-[inset_0_0_0_1px_rgba(20,111,90,0.18)]"
                  : "border-life-line bg-background text-life-ink",
                !alreadyAnswered &&
                  "hover:border-life-accent/60 hover:bg-life-accent-soft/40",
                alreadyAnswered && !selected && "opacity-70",
                submitting && "disabled:opacity-50",
              )}
            >
              <span
                className={cn(
                  "mt-px flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold",
                  selected
                    ? "bg-life-accent text-white"
                    : "bg-life-bg text-life-ink-3",
                )}
              >
                {selected ? <CheckIcon className="size-3.5" /> : i + 1}
              </span>
              <span className="min-w-0 flex-1">{option}</span>
              {selected && (
                <span className="shrink-0 rounded-full bg-life-accent px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.5px] text-white">
                  Selected
                </span>
              )}
            </button>
          );
        })}

        {hasCustomAnswer && (
          <div
            aria-label="Selected custom answer"
            className="mt-1 rounded-xl border border-life-accent bg-life-accent-soft px-3 py-2.5 text-[13px] text-life-ink shadow-[inset_0_0_0_1px_rgba(20,111,90,0.18)]"
          >
            <div className="mb-1 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.5px] text-life-accent">
              <CheckIcon className="size-3.5" />
              Custom answer selected
            </div>
            <div className="leading-snug">{normalizedSelectedAnswer}</div>
          </div>
        )}

        {allowFreeText && !alreadyAnswered && (
          <button
            type="button"
            disabled={submitting}
            aria-expanded={showCustom}
            aria-controls={customPanelId}
            onClick={() => setShowCustom((value) => !value)}
            className={cn(
              "mt-1 flex w-full items-center justify-between gap-3 rounded-xl border border-dashed border-life-line bg-transparent px-3 py-2.5 text-left text-[13px] text-life-ink-3 transition-colors",
              "hover:border-life-accent/60 hover:text-life-ink",
              "disabled:opacity-50",
            )}
          >
            <span>Write a different answer</span>
            <span aria-hidden="true">{showCustom ? "Hide" : "Open"}</span>
          </button>
        )}
      </div>

      {showCustom && !alreadyAnswered && (
        <div id={customPanelId} className="flex flex-col gap-2">
          <textarea
            value={customDraft}
            onChange={(e) => setCustomDraft(e.target.value)}
            placeholder="Tell me in your own words…"
            rows={3}
            disabled={submitting}
            className="w-full resize-none rounded-xl border border-life-line bg-background p-3 text-[14px] leading-relaxed text-life-ink outline-none focus:border-life-accent/60"
          />
          <div className="flex justify-end gap-2">
            <button
              type="button"
              disabled={submitting}
              onClick={() => {
                setShowCustom(false);
                setCustomDraft("");
              }}
              className="rounded-full px-4 py-2 text-[13px] text-life-ink-3 hover:text-life-ink disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={submitting || !customDraft.trim()}
              onClick={() => send(customDraft)}
              className={cn(
                "rounded-full bg-life-accent px-5 py-2 text-[13px] font-medium text-white",
                "disabled:opacity-50",
              )}
            >
              Send
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export const ChoiceCard = memo(ChoiceCardImpl) as ToolCallMessagePartComponent<
  AskUserChoiceArgs,
  AskUserChoiceResult | unknown
>;
