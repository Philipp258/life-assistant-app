import { useAuiState } from "@assistant-ui/react";
import { ChevronRightIcon, ListTodoIcon } from "lucide-react";
import { type FC } from "react";
import { Link } from "react-router-dom";

type TaskSource = {
  type: "task";
  task_id: number;
  task_title: string;
  source_session_id?: number | null;
};

function isTaskSource(value: unknown): value is TaskSource {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    v.type === "task" &&
    typeof v.task_id === "number" &&
    typeof v.task_title === "string"
  );
}

/**
 * Renders a compact linked provenance card above an assistant message that was
 * posted from a task chat via `notify_main_chat`. The
 * title links to the originating task so the user can jump straight into
 * the task chat for context.
 *
 * No-ops when the message has no task source metadata, so it is safe to
 * mount unconditionally on every assistant message.
 */
export const TaskSourceLine: FC = () => {
  // The external-store converter stamps backend provenance under
  // `metadata.custom.source` (assistant-ui normalises unknown top-level
  // metadata into `custom`); tolerate the legacy top-level shape too.
  const source = useAuiState((s) => {
    const meta = s.message.metadata as
      | { source?: unknown; custom?: { source?: unknown } }
      | undefined;
    return meta?.custom?.source ?? meta?.source;
  });

  if (!isTaskSource(source)) return null;

  return (
    <Link
      to={`/tasks/${source.task_id}`}
      data-slot="task-source-line"
      aria-label={`Open source task: ${source.task_title}`}
      className="group mb-2 flex w-fit max-w-full items-center gap-2 rounded-md border border-life-line bg-life-card px-2.5 py-1.5 text-[12px] text-life-ink-3 shadow-sm transition-colors hover:border-life-accent/60 hover:bg-life-accent-soft/40 hover:text-life-ink-2"
    >
      <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-life-accent-soft text-life-accent">
        <ListTodoIcon className="size-3.5" aria-hidden="true" />
      </span>
      <span className="min-w-0">
        <span className="block text-[11px] font-medium uppercase tracking-[0.6px] text-life-accent">
          Task notification
        </span>
        <span className="block truncate text-life-ink group-hover:underline">
          {source.task_title}
        </span>
      </span>
      <ChevronRightIcon
        className="size-3.5 shrink-0 text-life-ink-3 transition-transform group-hover:translate-x-0.5 group-hover:text-life-accent"
        aria-hidden="true"
      />
    </Link>
  );
};
