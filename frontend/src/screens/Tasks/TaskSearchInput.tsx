import { Search, X } from "lucide-react";
import { useEffect, useRef } from "react";

import { cn } from "@/lib/utils";

export type TaskSearchInputProps = {
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  /** Visual width. "auto" lets the input fill its parent. */
  width?: "auto" | "sm" | "md";
  autoFocus?: boolean;
  /** Called when the user presses Escape on an empty input. Useful for
   * expandable variants that want to collapse on Escape. */
  onEscapeWhenEmpty?: () => void;
  className?: string;
};

/** Single-purpose search input used by every TaskSearch variant. Keeps
 * placeholder, clear button, and Escape behaviour consistent. */
export function TaskSearchInput({
  value,
  onChange,
  placeholder = "Search tasks…",
  width = "auto",
  autoFocus = false,
  onEscapeWhenEmpty,
  className,
}: TaskSearchInputProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
  }, [autoFocus]);

  const widthClass =
    width === "sm" ? "w-40" : width === "md" ? "w-64" : "w-full";

  return (
    <div
      className={cn(
        "flex items-center gap-1.5 rounded-full border border-life-line bg-white px-2.5 py-1 text-[12.5px] focus-within:border-life-accent",
        widthClass,
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
          if (e.key === "Escape") {
            if (value === "") {
              onEscapeWhenEmpty?.();
            } else {
              onChange("");
            }
          }
        }}
        placeholder={placeholder}
        aria-label="Search tasks"
        className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-life-ink-3"
      />
      {value && (
        <button
          type="button"
          onClick={() => {
            onChange("");
            inputRef.current?.focus();
          }}
          aria-label="Clear search"
          className="shrink-0 rounded-full p-0.5 text-life-ink-3 hover:bg-life-bg hover:text-life-ink"
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}
