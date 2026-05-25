import type { ReactNode } from "react";

type HeaderProps = {
  title: string;
  subtitle?: string;
  right?: ReactNode;
  left?: ReactNode;
};

export function Header({ title, subtitle, right, left }: HeaderProps) {
  return (
    <div className="px-5 pt-11 pb-4">
      {left}
      <div className="flex items-end justify-between gap-3">
        <div className="min-w-0 flex-1">
          {subtitle && (
            <div className="mb-0.5 text-[12px] font-medium tracking-[0.6px] text-life-ink-3 uppercase">
              {subtitle}
            </div>
          )}
          <h1 className="m-0 font-serif text-[34px] leading-[1.1] font-normal tracking-[-0.5px] text-life-ink">
            {title}
          </h1>
        </div>
        {right}
      </div>
    </div>
  );
}
