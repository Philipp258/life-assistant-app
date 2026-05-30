import { X } from "lucide-react";

import { cn } from "@/lib/utils";

import type { FilterBlob } from "../savedTaskViewsApi";

type Props = {
  open: boolean;
  value: FilterBlob;
  assistantName?: string;
  onChange: (next: FilterBlob) => void;
  onClose: () => void;
};

type OwnerOption = { key: "any" | "user" | "assistant"; label: string };
type StatusValue = NonNullable<FilterBlob["statuses"]>[number];
const STATUSES: { key: StatusValue; label: string }[] = [
  { key: "open", label: "Open" },
  { key: "scheduled", label: "Scheduled" },
  { key: "waiting", label: "Waiting" },
];

type DueOption = { key: "any" | "today" | "week"; label: string };
const DUE_OPTIONS: DueOption[] = [
  { key: "any", label: "Any" },
  { key: "today", label: "Today" },
  { key: "week", label: "This week" },
];

export function FilterSheet({
  open,
  value,
  assistantName = "Assistant",
  onChange,
  onClose,
}: Props) {
  if (!open) return null;
  const owners: OwnerOption[] = [
    { key: "any", label: "Any" },
    { key: "user", label: "Mine" },
    { key: "assistant", label: assistantName },
  ];

  function setOwner(next: OwnerOption["key"]) {
    onChange({ assignee: next === "any" ? null : next });
  }

  function toggleStatus(status: StatusValue) {
    const set = new Set(value.statuses ?? []);
    if (set.has(status)) set.delete(status);
    else set.add(status);
    onChange({ statuses: [...set] });
  }

  function setDue(next: DueOption["key"]) {
    onChange({ due: next === "any" ? null : next });
  }

  const ownerKey: OwnerOption["key"] = value.assignee ?? "any";
  const dueKey: DueOption["key"] = value.due ?? "any";

  return (
    <div
      className="fixed inset-0 z-20 flex flex-col items-center bg-black/30"
      onClick={onClose}
    >
      <div
        className="mt-auto flex h-[78vh] w-full max-w-[420px] flex-col rounded-t-2xl bg-white"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-life-line px-3 py-2.5">
          <div className="text-[14px] font-semibold">Filters</div>
          <button type="button" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-3 py-3 text-[13px]">
          <Section title="Owner">
            <div className="flex gap-1">
              {owners.map((option) => (
                <button
                  key={option.key}
                  type="button"
                  onClick={() => setOwner(option.key)}
                  className={cn(
                    "flex-1 rounded-xl border px-2 py-1.5 text-[12px]",
                    ownerKey === option.key
                      ? "border-life-accent bg-life-accent text-white"
                      : "border-life-line bg-life-bg",
                  )}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </Section>
          <Section title="Status">
            <ChipRow>
              {STATUSES.map((option) => (
                <Chip
                  key={option.key}
                  on={value.statuses?.includes(option.key) ?? false}
                  onClick={() => toggleStatus(option.key)}
                >
                  {option.label}
                </Chip>
              ))}
            </ChipRow>
          </Section>
          <Section title="Date">
            <ChipRow>
              {DUE_OPTIONS.map((option) => (
                <Chip
                  key={option.key}
                  on={dueKey === option.key}
                  onClick={() => setDue(option.key)}
                >
                  {option.label}
                </Chip>
              ))}
            </ChipRow>
          </Section>
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-3">
      <div className="mb-1 text-[11px] uppercase tracking-wide text-life-ink-3">{title}</div>
      {children}
    </div>
  );
}

function ChipRow({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-wrap gap-1">{children}</div>;
}

function Chip({
  on,
  onClick,
  children,
}: {
  on: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full px-2 py-0.5 text-[12px]",
        on ? "bg-life-accent text-white" : "bg-life-bg text-life-ink-2",
      )}
    >
      {children}
    </button>
  );
}
