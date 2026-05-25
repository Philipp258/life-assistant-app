import type { CSSProperties, ReactNode } from "react";

import { cn } from "@/lib/utils";

type ChipProps = {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
};

/** Pill label — matches the Chip from design/components/shared.jsx. */
export function Chip({ children, className, style }: ChipProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-[3px] text-[11px] font-medium uppercase tracking-[0.2px] whitespace-nowrap",
        className,
      )}
      style={style}
    >
      {children}
    </span>
  );
}
