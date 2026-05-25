import { memo } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, Circle, LoaderIcon } from "lucide-react";
import type { ToolCallMessagePartComponent } from "@assistant-ui/react";

import { ToolFallback } from "@/components/assistant-ui/tool-fallback";
import { cn } from "@/lib/utils";
import { IconCaret } from "@/shell/icons";
import { useIdentity } from "@/shell/identity";
import { formatDoAt, formatInterval } from "@/screens/Tasks/format";
import type {
  Assignee,
  IntervalUnit,
  TaskState,
} from "@/screens/Tasks/tasksApi";

type CreateTaskArgs = {
  title?: string;
  description?: string | null;
  assignee?: Assignee;
  do_at?: string | null;
  interval_unit?: IntervalUnit | null;
  interval_count?: number | null;
};

type CreateTaskResult = {
  id: number;
  title: string;
  is_done: boolean;
  assignee: Assignee;
  state: TaskState;
  description: string | null;
  do_at: string | null;
  interval_unit: IntervalUnit | null;
  interval_count: number | null;
  chat_session_id: number;
};

const STATE_LABEL: Record<TaskState, string> = {
  running: "running",
  up_next: "up next",
  yours: "for you",
  done: "done",
};

function isCreateTaskResult(value: unknown): value is CreateTaskResult {
  return (
    !!value &&
    typeof value === "object" &&
    typeof (value as { id?: unknown }).id === "number" &&
    typeof (value as { title?: unknown }).title === "string"
  );
}

const TaskCreatedCardImpl: ToolCallMessagePartComponent<
  CreateTaskArgs,
  CreateTaskResult | unknown
> = (props) => {
  const { status, result, args } = props;
  const navigate = useNavigate();
  const { assistantName } = useIdentity();

  if (status?.type === "running") {
    return (
      <div
        data-slot="task-created-card-running"
        className="flex w-full items-center gap-2 rounded-2xl border border-life-line bg-life-card px-4 py-3 text-sm text-life-ink-3"
      >
        <LoaderIcon className="size-4 animate-spin text-life-accent" />
        <span>
          Creating task
          {args?.title ? (
            <>
              : <span className="text-life-ink-2">{args.title}</span>
            </>
          ) : null}
          …
        </span>
      </div>
    );
  }

  if (status?.type === "incomplete" || !isCreateTaskResult(result)) {
    return <ToolFallback {...props} />;
  }

  const open = () => navigate(`/tasks/${result.id}`);

  const ownerLabel = result.assignee === "assistant" ? assistantName : "You";
  const stateLabel = STATE_LABEL[result.state] ?? "task";
  const intervalLabel =
    result.interval_unit && result.interval_count !== null
      ? formatInterval(result.interval_unit, result.interval_count)
      : null;
  const doAtLabel = result.do_at ? formatDoAt(result.do_at) : null;
  const subParts = [
    ownerLabel,
    stateLabel,
    intervalLabel,
    doAtLabel,
  ].filter(Boolean) as string[];

  return (
    <button
      type="button"
      onClick={open}
      className={cn(
        "group/task-card flex w-full items-start gap-3 rounded-2xl border border-life-line bg-life-card p-[14px] text-left transition-colors",
        "hover:border-life-accent/60 hover:bg-life-accent-soft/40",
      )}
      aria-label={`Open task: ${result.title}`}
    >
      <div
        className={cn(
          "flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-[10px]",
          result.is_done
            ? "bg-life-done-soft text-life-done"
            : "bg-life-accent-soft text-life-accent",
        )}
      >
        {result.is_done ? (
          <CheckCircle2 className="size-5" />
        ) : (
          <Circle className="size-5" strokeWidth={2.2} />
        )}
      </div>

      <div className="min-w-0 flex-1">
        <div className="text-[10px] font-bold uppercase tracking-[0.6px] text-life-accent">
          Task created
        </div>
        <div className="mt-0.5 text-[15px] leading-tight font-medium text-life-ink">
          {result.title}
        </div>
        <div className="mt-1 text-[12px] text-life-ink-3">
          {subParts.join(" · ")}
        </div>
      </div>

      <span className="mt-1 text-life-ink-3 transition-transform group-hover/task-card:translate-x-0.5">
        <IconCaret />
      </span>
    </button>
  );
};

export const TaskCreatedCard = memo(
  TaskCreatedCardImpl,
) as ToolCallMessagePartComponent<CreateTaskArgs, CreateTaskResult | unknown>;
