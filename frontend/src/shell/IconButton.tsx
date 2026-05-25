import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/utils";

type IconButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> & {
  children: ReactNode;
  active?: boolean;
};

export function IconButton({
  children,
  active,
  className,
  type = "button",
  ...rest
}: IconButtonProps) {
  return (
    <button
      type={type}
      {...rest}
      className={cn(
        "flex h-9 w-9 items-center justify-center rounded-full border border-life-line",
        active
          ? "bg-life-accent text-white"
          : "bg-life-card text-life-ink-2",
        className,
      )}
    >
      {children}
    </button>
  );
}
