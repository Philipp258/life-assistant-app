import type { Meta, StoryObj } from "@storybook/react-vite";
import type { ComponentProps } from "react";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";

import { ChoiceCardView } from "./choice-card";

const meta = {
  title: "Assistant/Choice Card",
  component: ChoiceCardView,
  parameters: {
    layout: "centered",
  },
  decorators: [
    (Story) => (
      <MemoryRouter>
        <div className="w-[390px] max-w-[calc(100vw-32px)] bg-life-bg p-3 text-life-ink">
          <Story />
        </div>
      </MemoryRouter>
    ),
  ],
  args: {
    allowFreeText: true,
    alreadyAnswered: false,
    submitting: false,
  },
} satisfies Meta<typeof ChoiceCardView>;

export default meta;
type Story = StoryObj<typeof meta>;

const compactQuestion =
  "I found two likely interpretations. Which one should I use for the reminder?";

const markdownQuestion = `## Which implementation should I ship?

The current task has a few tradeoffs:

- **Option A** keeps the change narrow and updates only the visible choice card.
- **Option B** also revisits the surrounding chat layout, which could improve review but touches more code.
- **Option C** pauses so you can inspect the branch first.

Relevant context: the prompt came from \`ask_user_choice\` after task #284, where the long suggestions were hard to scan.`;

const verboseQuestion = `I can prepare the weekly planning task in a few different ways. Pick the version that matches how much structure you want.

### What I will include

- Current open commitments
- Calendar pressure for the next three days
- Follow-up tasks that have gone quiet
- A short "next action" for each suggested item

I will keep the final output concise after you choose a mode.`;

function InteractiveChoice(args: ComponentProps<typeof ChoiceCardView>) {
  const [submitted, setSubmitted] = useState<string | null>(null);
  const selectedAnswer = submitted ?? args.selectedAnswer ?? null;

  return (
    <div className="flex flex-col gap-3">
      <ChoiceCardView
        {...args}
        alreadyAnswered={submitted !== null || args.alreadyAnswered}
        selectedAnswer={selectedAnswer}
        onSubmit={setSubmitted}
      />
      {submitted && (
        <div className="ml-auto max-w-[82%] rounded-2xl rounded-tr-md bg-life-accent px-4 py-2 text-right text-[13px] font-medium text-white">
          {submitted}
        </div>
      )}
    </div>
  );
}

export const Compact: Story = {
  args: {
    question: compactQuestion,
    options: ["Create a morning reminder", "Create an evening reminder"],
    allowFreeText: false,
  },
  render: (args) => <InteractiveChoice {...args} />,
};

export const LongMarkdownPrompt: Story = {
  args: {
    question: markdownQuestion,
    options: [
      "Ship the narrow choice-card UI fix",
      "Broaden the chat layout cleanup",
      "Pause and let me review first",
    ],
    allowFreeText: true,
  },
  render: (args) => <InteractiveChoice {...args} />,
};

export const ManyOptionsWithFreeText: Story = {
  args: {
    question:
      "Which suggestion should I turn into the next task? You can also write a more specific instruction.",
    options: [
      "Draft the reply to Anna",
      "Create a grocery list for tonight",
      "Review the VPS backup schedule",
      "Plan tomorrow morning around the dentist call",
      "Summarize unread newsletters",
    ],
    allowFreeText: true,
  },
  render: (args) => <InteractiveChoice {...args} />,
};

export const VerboseLongCopy: Story = {
  args: {
    question: verboseQuestion,
    options: [
      "Make a short planning checklist",
      "Create detailed tasks with labels and due dates",
      "Only flag the highest-risk item",
    ],
    allowFreeText: true,
  },
  render: (args) => <InteractiveChoice {...args} />,
};

export const AnsweredWithOption: Story = {
  args: {
    question: markdownQuestion,
    options: [
      "Ship the narrow choice-card UI fix",
      "Broaden the chat layout cleanup",
      "Pause and let me review first",
    ],
    allowFreeText: true,
    alreadyAnswered: true,
    selectedAnswer: "Ship the narrow choice-card UI fix",
  },
};

export const AnsweredWithCustomText: Story = {
  args: {
    question:
      "Which suggestion should I turn into the next task? You can also write a more specific instruction.",
    options: [
      "Draft the reply to Anna",
      "Create a grocery list for tonight",
      "Review the VPS backup schedule",
    ],
    allowFreeText: true,
    alreadyAnswered: true,
    selectedAnswer: "Make this a Friday morning review and include the backup schedule.",
  },
};
