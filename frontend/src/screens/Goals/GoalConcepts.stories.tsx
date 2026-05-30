import type { Meta, StoryObj } from "@storybook/react-vite";
import {
  ArrowRight,
  Bell,
  Bot,
  CalendarClock,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Clock3,
  Home,
  ListChecks,
  MessageCircle,
  Pause,
  Plus,
  Target,
  User,
  Zap,
} from "lucide-react";
import { useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";
import { Header } from "@/shell/Header";

/**
 * Storybook-only product sketches for a goal layer above Tasks.
 *
 * The goal of these stories is not visual polish or schema design. They
 * show where "goals/projects/processes" could surface in the existing app:
 *
 * - Main chat remains the primary interface for updates, nudges, and
 *   decisions.
 * - A separate Goals surface makes long-running outcomes inspectable.
 * - Goal detail pages preserve state, problems, decisions, and linked tasks.
 * - Nudges are opt-in and happen in main chat, not as a separate inbox.
 * - A nested-task alternative is included for comparison.
 */

type GoalMode = "quiet" | "review" | "active";
type GoalState = "active" | "needs-input" | "watching";

type Goal = {
  id: number;
  title: string;
  area: string;
  outcome: string;
  state: GoalState;
  mode: GoalMode;
  current: string;
  problem: string;
  next: string;
  updated: string;
  progress: number;
};

const AC_GOAL: Goal = {
  id: 1,
  title: "Keep apartment cool efficiently",
  area: "Home",
  outcome: "Apartment stays comfortable in hot weather without wasting energy.",
  state: "needs-input",
  mode: "review",
  current: "Window outlet v1 is built and usable.",
  problem: "Warm air leaks around the panel and the hose angle is awkward.",
  next: "Run a 20 minute leak test and mark where heat enters.",
  updated: "Today 14:20",
  progress: 46,
};

const GOALS: Goal[] = [
  AC_GOAL,
  {
    id: 2,
    title: "Get back into steady running",
    area: "Health",
    outcome: "Run 3 times a week without knee pain.",
    state: "watching",
    mode: "quiet",
    current: "Two short runs logged last week.",
    problem: "No clear progression plan yet.",
    next: "Pick a light 4 week ramp and add the first run.",
    updated: "Yesterday",
    progress: 28,
  },
  {
    id: 3,
    title: "Prepare Q3 tax paperwork",
    area: "Finance",
    outcome: "All receipts and quarterly estimates are ready before the deadline.",
    state: "active",
    mode: "active",
    current: "Receipts folder exists; invoices are partially sorted.",
    problem: "Missing April bank export.",
    next: "Export April transactions from the bank portal.",
    updated: "Mon 09:10",
    progress: 62,
  },
];

const meta = {
  title: "Concepts/Goals",
  parameters: {
    layout: "centered",
    docs: {
      description: {
        component:
          "Mobile-first product sketches for introducing goals/projects above tasks. These are Storybook-only prototypes. They focus on how main chat, goal overview, goal detail, and task structure could work together.",
      },
    },
  },
} satisfies Meta;

export default meta;
type Story = StoryObj<typeof meta>;

export const A_ChatFirstGoalUpdate: Story = {
  render: () => (
    <PhoneFrame active="Chat">
      <ChatScreenFrame>
        <UserBubble>
          The AC window outlet works now, but I am unhappy with it. Warm air
          leaks around the side and the hose angle makes it annoying to close
          the curtain.
        </UserBubble>
        <AssistantBubble>
          I matched that to the home cooling goal and updated its current
          state. The task "Build window outlet v1" can stay done; the goal is
          not done.
        </AssistantBubble>
        <GoalUpdateCard goal={AC_GOAL} />
        <AssistantBubble>
          The next concrete move is a leak test, not buying more parts yet. I
          can make that a task, or just keep it as the goal's next step.
        </AssistantBubble>
        <ChoiceRow
          options={["Create task", "Keep as next step", "Open goal"]}
        />
      </ChatScreenFrame>
    </PhoneFrame>
  ),
};

export const B_GoalsOverview: Story = {
  render: () => (
    <PhoneFrame active="Goals">
      <div className="flex h-full flex-col bg-life-bg">
        <Header
          title="Goals"
          subtitle="OUTCOMES"
          right={
            <button
              type="button"
              className="flex h-9 w-9 items-center justify-center rounded-full bg-life-accent text-white"
              aria-label="New goal"
            >
              <Plus className="h-4 w-4" />
            </button>
          }
        />
        <div className="flex gap-2 overflow-x-auto border-b border-life-line px-5 pb-3">
          {["Active", "Needs decision", "Quiet", "Areas"].map((label, index) => (
            <button
              key={label}
              type="button"
              className={cn(
                "shrink-0 rounded-full border px-3 py-1.5 text-[12px] font-medium",
                index === 0
                  ? "border-life-accent bg-life-accent text-white"
                  : "border-life-line bg-life-card text-life-ink-2",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <SectionLabel>Needs attention</SectionLabel>
          <div className="mb-5 flex flex-col gap-3">
            <GoalListCard goal={AC_GOAL} prominent />
          </div>
          <SectionLabel>In motion</SectionLabel>
          <div className="flex flex-col gap-3">
            {GOALS.slice(1).map((goal) => (
              <GoalListCard key={goal.id} goal={goal} />
            ))}
          </div>
        </div>
      </div>
    </PhoneFrame>
  ),
};

export const C_GoalDetail: Story = {
  render: () => (
    <PhoneFrame active="Goals">
      <div className="flex h-full flex-col bg-life-bg">
        <div className="border-b border-life-line bg-life-card px-4 pt-11 pb-3">
          <button
            type="button"
            className="mb-2 inline-flex items-center gap-1 text-[12px] text-life-ink-3"
          >
            <ArrowRight className="h-3.5 w-3.5 rotate-180" />
            Goals
          </button>
          <div className="mb-1 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.6px] text-life-ink-3">
            <Home className="h-3.5 w-3.5" />
            Home
            <StatusToken state={AC_GOAL.state} />
          </div>
          <h1 className="font-serif text-[28px] leading-tight text-life-ink">
            {AC_GOAL.title}
          </h1>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <GoalSummaryPanel goal={AC_GOAL} />
          <SectionLabel className="mt-5">Next move</SectionLabel>
          <NextMovePanel />
          <SectionLabel className="mt-5">Linked tasks</SectionLabel>
          <LinkedTaskList />
          <SectionLabel className="mt-5">Goal log</SectionLabel>
          <GoalLog />
        </div>
      </div>
    </PhoneFrame>
  ),
};

export const D_MainChatReviewNudge: Story = {
  render: () => <ReviewNudgeStory />,
};

export const E_NestedTaskAlternative: Story = {
  render: () => (
    <PhoneFrame active="Tasks">
      <div className="flex h-full flex-col bg-life-bg">
        <Header title="Tasks" subtitle="TASKS" />
        <div className="border-y border-life-line bg-life-card px-5 py-2 text-[12px] text-life-ink-3">
          Alternative sketch: a parent task acts like the goal. No separate
          Goals tab, but the distinction between "done task" and "done
          outcome" is weaker.
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <ParentTaskCard />
        </div>
      </div>
    </PhoneFrame>
  ),
};

function ReviewNudgeStory() {
  const [mode, setMode] = useState<GoalMode>("review");

  return (
    <PhoneFrame active="Chat">
      <ChatScreenFrame>
        <AssistantBubble>
          Goal review: your home cooling setup has one open problem from the
          last update.
        </AssistantBubble>
        <NudgeCard mode={mode} onModeChange={setMode} />
        <UserBubble>Make the leak test a task for Saturday morning.</UserBubble>
        <AssistantBubble>
          Done. I created a scheduled task linked to the cooling goal. I will
          bring the result back here when it is time.
        </AssistantBubble>
        <MiniTaskCard />
      </ChatScreenFrame>
    </PhoneFrame>
  );
}

function PhoneFrame({
  children,
  active,
}: {
  children: ReactNode;
  active: "Chat" | "Tasks" | "Goals";
}) {
  return (
    <div className="mx-auto flex h-[700px] w-full max-w-[390px] flex-col overflow-hidden rounded-2xl border border-life-line bg-life-bg shadow-sm">
      <div className="min-h-0 flex-1 overflow-hidden">{children}</div>
      <ConceptTabBar active={active} />
    </div>
  );
}

function ConceptTabBar({ active }: { active: "Chat" | "Tasks" | "Goals" }) {
  const tabs: { label: "Chat" | "Tasks" | "Goals" | "Know"; icon: ReactNode }[] = [
    { label: "Chat", icon: <MessageCircle className="h-4 w-4" /> },
    { label: "Tasks", icon: <ListChecks className="h-4 w-4" /> },
    { label: "Goals", icon: <Target className="h-4 w-4" /> },
    { label: "Know", icon: <CircleDot className="h-4 w-4" /> },
  ];
  return (
    <nav className="flex shrink-0 border-t border-life-line bg-life-card/90 px-1.5 pt-2 pb-3">
      {tabs.map((tab) => {
        const on = tab.label === active;
        return (
          <button
            key={tab.label}
            type="button"
            className={cn(
              "flex min-h-[54px] flex-1 flex-col items-center justify-center gap-0.5 rounded-2xl text-[10px] font-semibold",
              on ? "bg-life-card text-life-accent" : "text-life-ink-3",
            )}
          >
            {tab.icon}
            {tab.label}
          </button>
        );
      })}
    </nav>
  );
}

function ChatScreenFrame({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-full flex-col bg-life-bg">
      <header className="flex items-center justify-between border-b border-life-line px-4 py-3">
        <span className="text-sm font-semibold text-life-ink">Assistant</span>
        <span className="rounded-full border border-life-line bg-life-card px-2 py-0.5 text-[11px] text-life-ink-3">
          Main chat
        </span>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5">
        <div className="flex flex-col gap-4">{children}</div>
      </div>
      <div className="border-t border-life-line bg-life-card px-4 py-3">
        <div className="flex items-center gap-2 rounded-2xl border border-life-line bg-white px-3 py-2 text-[13px] text-life-ink-3">
          Send a message...
          <button
            type="button"
            className="ml-auto flex h-7 w-7 items-center justify-center rounded-full bg-life-accent text-white"
            aria-label="Send"
          >
            <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}

function UserBubble({ children }: { children: ReactNode }) {
  return (
    <div className="ml-auto max-w-[82%] rounded-2xl bg-life-card px-4 py-2.5 text-[13px] leading-relaxed text-life-ink-2">
      {children}
    </div>
  );
}

function AssistantBubble({ children }: { children: ReactNode }) {
  return (
    <div className="mr-auto flex max-w-[92%] gap-2">
      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-life-accent-soft text-life-accent">
        <Bot className="h-3.5 w-3.5" />
      </span>
      <div className="rounded-2xl bg-transparent px-1 py-1 text-[13px] leading-relaxed text-life-ink-2">
        {children}
      </div>
    </div>
  );
}

function GoalUpdateCard({ goal }: { goal: Goal }) {
  return (
    <div className="ml-9 rounded-lg border border-life-line bg-life-card p-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-[0.6px] text-life-accent">
            Goal updated
          </div>
          <div className="text-[15px] font-semibold leading-tight text-life-ink">
            {goal.title}
          </div>
        </div>
        <StatusToken state={goal.state} />
      </div>
      <KeyValue label="Current" value={goal.current} />
      <KeyValue label="Problem" value={goal.problem} />
      <KeyValue label="Next" value={goal.next} />
    </div>
  );
}

function ChoiceRow({
  options,
  inset = true,
  className,
}: {
  options: string[];
  inset?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap gap-1.5", inset && "ml-9", className)}>
      {options.map((option, index) => (
        <button
          key={option}
          type="button"
          className={cn(
            "rounded-full border px-3 py-1.5 text-[12px] font-medium",
            index === 0
              ? "border-life-accent bg-life-accent text-white"
              : "border-life-line bg-life-card text-life-ink-2",
          )}
        >
          {option}
        </button>
      ))}
    </div>
  );
}

function GoalListCard({
  goal,
  prominent = false,
}: {
  goal: Goal;
  prominent?: boolean;
}) {
  return (
    <button
      type="button"
      className={cn(
        "w-full rounded-lg border bg-life-card p-3 text-left",
        prominent ? "border-amber-300" : "border-life-line",
      )}
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-life-ink-3">
            <Home className="h-3 w-3" />
            {goal.area}
          </div>
          <div className="text-[15px] font-semibold leading-tight text-life-ink">
            {goal.title}
          </div>
        </div>
        <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-life-ink-3" />
      </div>
      <p className="mb-2 line-clamp-2 text-[12px] leading-relaxed text-life-ink-2">
        {goal.outcome}
      </p>
      <ProgressLine value={goal.progress} />
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <StatusToken state={goal.state} />
        <ModeToken mode={goal.mode} />
        <span className="text-[11px] text-life-ink-3">{goal.updated}</span>
      </div>
      <div className="mt-2 rounded-md bg-life-bg px-2 py-1.5 text-[12px] text-life-ink-2">
        Next: {goal.next}
      </div>
    </button>
  );
}

function GoalSummaryPanel({ goal }: { goal: Goal }) {
  return (
    <section className="rounded-lg border border-life-line bg-life-card p-3">
      <KeyValue label="Outcome" value={goal.outcome} />
      <KeyValue label="Current state" value={goal.current} />
      <KeyValue label="Known problem" value={goal.problem} />
      <div className="mt-3">
        <ProgressLine value={goal.progress} />
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        <ModeToken mode={goal.mode} />
        <span className="rounded-full bg-life-bg px-2 py-0.5 text-[11px] text-life-ink-3">
          Updated {goal.updated}
        </span>
      </div>
    </section>
  );
}

function NextMovePanel() {
  return (
    <section className="rounded-lg border border-life-line bg-life-card p-3">
      <div className="mb-2 flex items-center gap-2">
        <Zap className="h-4 w-4 text-life-accent" />
        <div className="text-[14px] font-semibold text-life-ink">
          Run a leak test
        </div>
      </div>
      <p className="text-[12px] leading-relaxed text-life-ink-2">
        Tape paper strips around the panel, run the AC for 20 minutes, and
        mark every place where warm air moves inward.
      </p>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          className="rounded-full bg-life-accent px-3 py-1.5 text-[12px] font-medium text-white"
        >
          Create task
        </button>
        <button
          type="button"
          className="rounded-full border border-life-line bg-white px-3 py-1.5 text-[12px] font-medium text-life-ink-2"
        >
          Change next
        </button>
      </div>
    </section>
  );
}

function LinkedTaskList() {
  const tasks = [
    {
      title: "Buy hose adapter and foam board",
      status: "Done",
      icon: <CheckCircle2 className="h-3.5 w-3.5" />,
    },
    {
      title: "Build window outlet v1",
      status: "Done",
      icon: <CheckCircle2 className="h-3.5 w-3.5" />,
    },
    {
      title: "Leak-test the AC outlet",
      status: "Suggested",
      icon: <Clock3 className="h-3.5 w-3.5" />,
    },
  ];
  return (
    <div className="divide-y divide-life-line rounded-lg border border-life-line bg-life-card">
      {tasks.map((task) => (
        <div key={task.title} className="flex items-center gap-2 px-3 py-2.5">
          <span
            className={cn(
              "flex h-6 w-6 shrink-0 items-center justify-center rounded-full",
              task.status === "Done"
                ? "bg-life-done-soft text-life-done"
                : "bg-life-scheduled-soft text-life-scheduled",
            )}
          >
            {task.icon}
          </span>
          <span className="min-w-0 flex-1 text-[13px] text-life-ink-2">
            {task.title}
          </span>
          <span className="text-[11px] text-life-ink-3">{task.status}</span>
        </div>
      ))}
    </div>
  );
}

function GoalLog() {
  const entries = [
    {
      at: "Today",
      text: "User reported v1 works but leaks warm air and blocks curtain.",
    },
    {
      at: "Sat",
      text: "Task completed: built first window outlet from foam board.",
    },
    {
      at: "Fri",
      text: "Goal created from chat about making the AC setup efficient.",
    },
  ];
  return (
    <div className="flex flex-col gap-2">
      {entries.map((entry) => (
        <div
          key={`${entry.at}-${entry.text}`}
          className="rounded-lg border border-life-line bg-life-card px-3 py-2.5"
        >
          <div className="mb-0.5 text-[11px] font-medium text-life-ink-3">
            {entry.at}
          </div>
          <div className="text-[12px] leading-relaxed text-life-ink-2">
            {entry.text}
          </div>
        </div>
      ))}
    </div>
  );
}

function NudgeCard({
  mode,
  onModeChange,
}: {
  mode: GoalMode;
  onModeChange: (mode: GoalMode) => void;
}) {
  return (
    <div className="ml-9 rounded-lg border border-life-line bg-life-card p-3">
      <div className="mb-2 flex items-center gap-2">
        <Bell className="h-4 w-4 text-life-accent" />
        <div>
          <div className="text-[10px] font-bold uppercase tracking-[0.6px] text-life-accent">
            Opt-in nudge
          </div>
          <div className="text-[15px] font-semibold leading-tight text-life-ink">
            {AC_GOAL.title}
          </div>
        </div>
      </div>
      <p className="text-[12px] leading-relaxed text-life-ink-2">
        You set this goal to review mode. I should only raise it when there
        is a concrete next move or a scheduled review.
      </p>
      <div className="mt-3 rounded-md bg-life-bg px-2 py-1.5 text-[12px] text-life-ink-2">
        Suggested next task: leak-test the outlet Saturday morning.
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {(["quiet", "review", "active"] as const).map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => onModeChange(value)}
            className={cn(
              "rounded-full border px-2.5 py-1 text-[11px] font-medium capitalize",
              mode === value
                ? "border-life-accent bg-life-accent text-white"
                : "border-life-line bg-white text-life-ink-2",
            )}
          >
            {value}
          </button>
        ))}
      </div>
      <ChoiceRow
        options={["Make task", "Remind later", "Stay quiet"]}
        inset={false}
        className="mt-3"
      />
    </div>
  );
}

function MiniTaskCard() {
  return (
    <div className="ml-9 flex items-start gap-3 rounded-lg border border-life-line bg-life-card p-3">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-life-scheduled-soft text-life-scheduled">
        <CalendarClock className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[10px] font-bold uppercase tracking-[0.6px] text-life-accent">
          Task created
        </div>
        <div className="text-[14px] font-semibold text-life-ink">
          Leak-test the AC outlet
        </div>
        <div className="text-[12px] text-life-ink-3">
          Saturday 09:00 - linked to cooling goal
        </div>
      </div>
    </div>
  );
}

function ParentTaskCard() {
  return (
    <section className="rounded-lg border border-life-line bg-life-card">
      <div className="border-b border-life-line p-3">
        <div className="mb-1 flex items-center gap-2 text-[11px] font-medium text-life-ink-3">
          <Target className="h-3.5 w-3.5" />
          Parent task
        </div>
        <div className="text-[16px] font-semibold text-life-ink">
          Keep apartment cool efficiently
        </div>
        <p className="mt-1 text-[12px] leading-relaxed text-life-ink-2">
          Outcome and project state live in this parent task description.
          Child tasks show progress.
        </p>
      </div>
      <NestedTask title="Buy hose adapter and foam board" done />
      <NestedTask title="Build window outlet v1" done />
      <NestedTask title="Leak-test the AC outlet" />
      <div className="border-t border-life-line bg-life-bg px-3 py-2 text-[12px] text-life-ink-3">
        Weak point: if every parent can be a goal, the task list needs rules
        for when checking children should update the parent.
      </div>
    </section>
  );
}

function NestedTask({ title, done = false }: { title: string; done?: boolean }) {
  return (
    <div className="flex items-center gap-2 border-b border-life-line px-3 py-2.5 last:border-b-0">
      <span
        className={cn(
          "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border",
          done
            ? "border-life-done bg-life-done text-white"
            : "border-life-ink-3/40 text-transparent",
        )}
      >
        <CheckCircle2 className="h-3.5 w-3.5" />
      </span>
      <span
        className={cn(
          "min-w-0 flex-1 text-[13px]",
          done ? "text-life-ink-3 line-through" : "text-life-ink-2",
        )}
      >
        {title}
      </span>
      <User className="h-3.5 w-3.5 text-life-ink-3" />
    </div>
  );
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="mb-2 last:mb-0">
      <div className="text-[10px] font-semibold uppercase tracking-[0.5px] text-life-ink-3">
        {label}
      </div>
      <div className="text-[12px] leading-relaxed text-life-ink-2">
        {value}
      </div>
    </div>
  );
}

function SectionLabel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <h2
      className={cn(
        "mb-2 text-[10px] font-bold uppercase tracking-[0.6px] text-life-ink-3",
        className,
      )}
    >
      {children}
    </h2>
  );
}

function StatusToken({ state }: { state: GoalState }) {
  const label =
    state === "needs-input"
      ? "Needs decision"
      : state === "watching"
        ? "Watching"
        : "Active";
  return (
    <span
      className={cn(
        "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold",
        state === "needs-input" && "bg-amber-100 text-amber-700",
        state === "watching" && "bg-life-scheduled-soft text-life-scheduled",
        state === "active" && "bg-life-done-soft text-life-done",
      )}
    >
      {label}
    </span>
  );
}

function ModeToken({ mode }: { mode: GoalMode }) {
  const label =
    mode === "quiet" ? "Quiet" : mode === "review" ? "Review mode" : "Active nudges";
  const icon =
    mode === "quiet" ? (
      <Pause className="h-3 w-3" />
    ) : mode === "review" ? (
      <Clock3 className="h-3 w-3" />
    ) : (
      <Bell className="h-3 w-3" />
    );
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-life-bg px-2 py-0.5 text-[11px] text-life-ink-3">
      {icon}
      {label}
    </span>
  );
}

function ProgressLine({ value }: { value: number }) {
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-life-line">
      <div
        className="h-full rounded-full bg-life-accent"
        style={{ width: `${value}%` }}
      />
    </div>
  );
}
