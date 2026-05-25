import { Search, X } from "lucide-react";
import { useEffect, useRef } from "react";

import { cn } from "@/lib/utils";

export type KnowledgeSearchInputProps = {
  value: string;
  onChange: (next: string) => void;
  /** Fired on Enter (form submit). Knowledge search runs on submit, not on
   * every keystroke — the query reads file bodies server-side. */
  onSubmit: (query: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
  className?: string;
};

/** Search input for the Knowledge tab. Unlike the Tasks search (live filter
 * over already-loaded rows), this submits on Enter because matching looks
 * inside document bodies on the server. Clearing resets to the tree. */
export function KnowledgeSearchInput({
  value,
  onChange,
  onSubmit,
  placeholder = "Search knowledge…",
  autoFocus = false,
  className,
}: KnowledgeSearchInputProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
  }, [autoFocus]);

  return (
    <form
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(value);
      }}
      className={cn(
        "flex w-full items-center gap-1.5 rounded-full border border-life-line bg-white px-2.5 py-1 text-[12.5px] focus-within:border-life-accent",
        className,
      )}
    >
      <Search className="h-3.5 w-3.5 shrink-0 text-life-ink-3" aria-hidden />
      <input
        ref={inputRef}
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape" && value !== "") {
            e.preventDefault();
            onChange("");
            onSubmit("");
          }
        }}
        placeholder={placeholder}
        aria-label="Search knowledge"
        className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-life-ink-3"
      />
      {value && (
        <button
          type="button"
          onClick={() => {
            onChange("");
            onSubmit("");
            inputRef.current?.focus();
          }}
          aria-label="Clear search"
          className="shrink-0 rounded-full p-0.5 text-life-ink-3 hover:bg-life-bg hover:text-life-ink"
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </form>
  );
}
