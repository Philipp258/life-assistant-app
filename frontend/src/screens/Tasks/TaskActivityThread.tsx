import {
  ActionBarPrimitive,
  AssistantRuntimeProvider,
  AuiIf,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAui,
  useAuiState,
} from "@assistant-ui/react";
import {
  ArrowUpIcon,
  Bot,
  CopyIcon,
  PencilIcon,
  RefreshCwIcon,
  User,
} from "lucide-react";
import {
  useRef,
  useState,
  type FC,
  type KeyboardEventHandler,
  type MutableRefObject,
  type ReactNode,
} from "react";

import { assistantMessagePartComponents } from "@/components/assistant-ui/message-parts";
import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";
import { Button } from "@/components/ui/button";
import { useIdentity } from "@/shell/identity";

import type { WireMessage } from "../Chat/convertChatMessage";
import { useChatChannelRuntime } from "../Chat/useChatChannel";
import { useLocalSendScroll } from "../Chat/useLocalSendScroll";
import type { Task } from "./tasksApi";

/**
 * Activity thread for the task detail page.
 *
 * Reuses the real assistant chat runtime + primitives — only the outer
 * message chrome differs from the production chat thread, so markdown,
 * reasoning, tool calls and first-class tool cards keep rendering through
 * the shared `assistantMessagePartComponents` map.
 *
 * The thread's viewport owns the page scroll: callers pass a `before` slot
 * (typically task metadata + description) which is rendered above the
 * message list, inside the same scrollable surface, so the whole task
 * detail reads as one linear page with a sticky composer at the bottom.
 */
export function TaskActivityThread({
  task,
  sessionId,
  initialMessages,
  before,
  heading,
}: {
  task: Task;
  sessionId: number;
  initialMessages: WireMessage[];
  before?: ReactNode;
  heading?: ReactNode;
}) {
  const { assistantName } = useIdentity();
  const [localSendVersion, setLocalSendVersion] = useState(0);
  const { runtime, messages } = useChatChannelRuntime({
    sessionId,
    initialMessages,
    onLocalSend: () => setLocalSendVersion((version) => version + 1),
  });
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const replySpacerHeight = useLocalSendScroll({
    viewportRef,
    messages,
    localSendVersion,
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ActivityView
        task={task}
        assistantName={assistantName}
        before={before}
        heading={heading}
        viewportRef={viewportRef}
        replySpacerHeight={replySpacerHeight}
      />
    </AssistantRuntimeProvider>
  );
}

function ActivityView({
  task,
  assistantName,
  before,
  heading,
  viewportRef,
  replySpacerHeight,
}: {
  task: Task;
  assistantName: string;
  before?: ReactNode;
  heading?: ReactNode;
  viewportRef: MutableRefObject<HTMLDivElement | null>;
  replySpacerHeight: number;
}) {
  const runnerActive = useAuiState((s) => s.thread.isRunning);
  return (
    <>
      <ThreadPrimitive.Root
        className="flex min-h-0 flex-1 flex-col"
        style={{
          ["--thread-max-width" as string]: "44rem",
          ["--composer-radius" as string]: "12px",
          ["--composer-padding" as string]: "10px",
        }}
      >
        <ThreadPrimitive.Viewport
          ref={viewportRef}
          turnAnchor="bottom"
          autoScroll={false}
          scrollToBottomOnRunStart={false}
          className="relative flex flex-1 flex-col overflow-y-auto"
          style={{ overflowAnchor: "none" }}
        >
          <div className="mx-auto flex w-full max-w-(--thread-max-width) flex-1 flex-col px-4 pt-4 pb-4 sm:px-5">
            {before ? <div className="flex flex-col gap-4">{before}</div> : null}

            {heading ? (
              <div className="mt-5 mb-1">{heading}</div>
            ) : null}

            <AuiIf condition={(s) => s.thread.isEmpty}>
              <ActivityEmpty
                task={task}
                runnerActive={runnerActive}
                assistantName={assistantName}
              />
            </AuiIf>

            <ol
              data-slot="aui_task-activity-thread"
              className="flex flex-col"
            >
              <ThreadPrimitive.Messages
                components={{
                  UserMessage: UserComment,
                  AssistantMessage: AssistantComment,
                  EditComposer: EditComposer,
                }}
              />
            </ol>
            <ReplySpacer height={replySpacerHeight} />

            <ThreadPrimitive.ViewportFooter
              data-slot="aui_task-viewport-footer"
              className="sticky bottom-0 mt-auto flex flex-col gap-2 bg-life-bg pt-3 pb-4"
            >
              <CommentComposer
                placeholder={composerPlaceholder(task, assistantName)}
              />
            </ThreadPrimitive.ViewportFooter>
          </div>
        </ThreadPrimitive.Viewport>
      </ThreadPrimitive.Root>
    </>
  );
}

const ReplySpacer: FC<{ height: number }> = ({ height }) => {
  if (height <= 0) return null;
  return (
    <div
      aria-hidden="true"
      data-slot="aui_local-reply-spacer"
      className="shrink-0"
      style={{ height }}
    />
  );
};

function composerPlaceholder(
  task: Pick<Task, "is_done" | "assignee">,
  assistantName: string,
): string {
  if (task.is_done) return "Add a note about what was done…";
  if (task.assignee === "assistant") return `Ask ${assistantName} a follow-up…`;
  return "Add a comment for yourself…";
}

function ActivityEmpty({
  task,
  runnerActive,
  assistantName,
}: {
  task: Task;
  runnerActive: boolean;
  assistantName: string;
}) {
  const [headline, sub] = runnerActive
    ? [`${assistantName} started running.`, "Activity will appear here as it is saved."]
    : task.assignee === "assistant"
      ? [`${assistantName} is on it.`, "Ask a question or hand it back to yourself."]
      : ["This one's on you.", `Hand it to ${assistantName} when you're ready.`];
  return (
    <div className="fade-in animate-in py-6 text-life-ink-3 duration-200">
      <p className="text-[14px] font-semibold text-life-ink-2">{headline}</p>
      <p className="text-[13px]">{sub}</p>
    </div>
  );
}

const UserComment: FC = () => {
  return (
    <CommentRow
      avatar={
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-life-line/60 text-life-ink-2">
          <User className="h-3.5 w-3.5" />
        </span>
      }
      header={
        <CommentHeader
          author="You"
          actions={
            <ActionBarPrimitive.Root
              hideWhenRunning
              autohide="not-last"
              className="flex gap-0.5 text-life-ink-3"
            >
              <ActionBarPrimitive.Edit
                render={<TooltipIconButton tooltip="Edit" />}
              >
                <PencilIcon />
              </ActionBarPrimitive.Edit>
            </ActionBarPrimitive.Root>
          }
        />
      }
    >
      <div className="prose-sm wrap-break-word text-[13px] leading-relaxed text-life-ink-2">
        <MessagePrimitive.Parts />
      </div>
    </CommentRow>
  );
};

const AssistantComment: FC = () => {
  return (
    <CommentRow
      avatar={
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-life-accent-soft text-life-accent">
          <Bot className="h-3.5 w-3.5" />
        </span>
      }
      header={
        <CommentHeader
          author={useIdentity().assistantName}
          actions={
            <ActionBarPrimitive.Root
              hideWhenRunning
              autohide="not-last"
              className="flex gap-0.5 text-life-ink-3"
            >
              <ActionBarPrimitive.Copy
                render={<TooltipIconButton tooltip="Copy" />}
              >
                <CopyIcon />
              </ActionBarPrimitive.Copy>
              <ActionBarPrimitive.Reload
                render={<TooltipIconButton tooltip="Regenerate" />}
              >
                <RefreshCwIcon />
              </ActionBarPrimitive.Reload>
            </ActionBarPrimitive.Root>
          }
        />
      }
    >
      <div
        data-slot="aui_assistant-comment-body"
        className="wrap-break-word text-[13px] leading-relaxed text-life-ink-2"
      >
        <MessagePrimitive.Parts components={assistantMessagePartComponents} />
      </div>
    </CommentRow>
  );
};

const EditComposer: FC = () => {
  return (
    <li className="my-2 flex gap-3 px-1">
      <span className="w-7 shrink-0" aria-hidden />
      <ComposerPrimitive.Root className="flex flex-1 flex-col rounded-xl border border-life-line bg-life-card">
        <ComposerPrimitive.Input
          className="min-h-14 w-full resize-none bg-transparent px-3 py-2 text-[13px] text-life-ink outline-none"
          autoFocus
        />
        <div className="flex items-center justify-end gap-2 border-t border-life-line px-3 py-2">
          <ComposerPrimitive.Cancel
            render={<Button variant="ghost" size="sm" />}
          >
            Cancel
          </ComposerPrimitive.Cancel>
          <ComposerPrimitive.Send render={<Button size="sm" />}>
            Update
          </ComposerPrimitive.Send>
        </div>
      </ComposerPrimitive.Root>
    </li>
  );
};

function CommentRow({
  avatar,
  header,
  children,
}: {
  avatar: ReactNode;
  header: ReactNode;
  children: ReactNode;
}) {
  return (
    <MessagePrimitive.Root
      data-slot="aui_comment-row"
      className="fade-in slide-in-from-bottom-1 flex animate-in gap-3 py-3 duration-150"
    >
      <div className="flex flex-col items-center">{avatar}</div>
      <article className="min-w-0 flex-1 rounded-xl border border-life-line bg-life-card">
        {header}
        <div className="px-3 py-2.5">{children}</div>
      </article>
    </MessagePrimitive.Root>
  );
}

function CommentHeader({
  author,
  actions,
}: {
  author: string;
  actions?: ReactNode;
}) {
  return (
    <header className="flex items-center justify-between gap-3 border-b border-life-line px-3 py-1.5">
      <div className="flex items-baseline gap-2 text-[12px]">
        <span className="font-semibold text-life-ink">{author}</span>
        <RelativeTimestamp />
      </div>
      <div className="flex items-center gap-1">{actions}</div>
    </header>
  );
}

const RelativeTimestamp: FC = () => {
  const at = useAuiState((s) => s.message.createdAt);
  if (!at) return null;
  return (
    <time
      className="text-life-ink-3"
      dateTime={typeof at === "string" ? at : new Date(at).toISOString()}
    >
      {formatRelative(at)}
    </time>
  );
};

function formatRelative(at: string | number | Date): string {
  const t =
    typeof at === "string"
      ? new Date(at).getTime()
      : new Date(at).getTime();
  const now = Date.now();
  const delta = Math.max(0, now - t);
  const sec = Math.round(delta / 1000);
  if (sec < 60) return "just now";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.round(hr / 24);
  return `${day}d ago`;
}

function CommentComposer({ placeholder }: { placeholder: string }) {
  const aui = useAui();
  const isEmpty = useAuiState((s) => s.composer.isEmpty);
  const isRunning = useAuiState((s) => s.thread.isRunning);

  const handleKeyDown: KeyboardEventHandler<HTMLTextAreaElement> = (e) => {
    // Allow posting while a turn runs (it queues for the next turn);
    // assistant-ui would otherwise swallow the submit key. Skip during IME
    // composition (Android keystroke-drop bug).
    if (
      isRunning &&
      e.key === "Enter" &&
      !e.shiftKey &&
      !e.nativeEvent.isComposing
    ) {
      e.preventDefault();
      void aui.thread().composer().send();
    }
  };

  return (
    <ComposerPrimitive.Root className="relative flex w-full flex-col rounded-xl border border-life-line bg-life-card transition-shadow focus-within:border-life-accent/60 focus-within:ring-2 focus-within:ring-life-accent/20">
      <ComposerPrimitive.Input
        placeholder={placeholder}
        className="min-h-[64px] w-full resize-none rounded-t-xl bg-transparent px-3 py-2 text-[13px] text-life-ink outline-none placeholder:text-life-ink-3"
        rows={2}
        aria-label="Add a comment"
        onKeyDown={handleKeyDown}
      />
      <div className="flex items-center justify-between border-t border-life-line px-3 py-2">
        <span className="text-[11px] text-life-ink-3">⌘ + Enter to post</span>
        <div className="flex items-center gap-2">
          {isRunning && (
            <span
              className="flex items-center gap-1 text-life-ink-3"
              role="status"
              aria-label="Assistant is working"
            >
              <span className="size-1.5 animate-pulse rounded-full bg-current" />
              <span className="size-1.5 animate-pulse rounded-full bg-current [animation-delay:150ms]" />
              <span className="size-1.5 animate-pulse rounded-full bg-current [animation-delay:300ms]" />
            </span>
          )}
          <Button
            size="sm"
            className="gap-1.5 rounded-full"
            disabled={isEmpty}
            onClick={() => void aui.thread().composer().send()}
          >
            <ArrowUpIcon className="h-3.5 w-3.5" />
            Comment
          </Button>
        </div>
      </div>
    </ComposerPrimitive.Root>
  );
}
