import type { Meta, StoryObj } from "@storybook/react-vite";

import { Chip } from "./Chip";

const meta = {
  title: "Shell/Chip",
  component: Chip,
  parameters: {
    layout: "centered",
  },
  tags: ["autodocs"],
  args: {
    children: "Status",
  },
} satisfies Meta<typeof Chip>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Done: Story = {
  args: {
    children: "Done",
    className: "bg-life-done-soft text-life-done",
  },
};

export const Scheduled: Story = {
  args: {
    children: "Scheduled",
    className: "bg-life-scheduled-soft text-life-scheduled",
  },
};

export const Recurring: Story = {
  args: {
    children: "Recurring",
    className: "bg-life-recurring-soft text-life-recurring",
  },
};

export const Accent: Story = {
  args: {
    children: "Active",
    className: "bg-life-accent-soft text-life-accent",
  },
};

export const Gallery: Story = {
  render: () => (
    <div className="flex flex-wrap items-center gap-2">
      <Chip className="bg-life-done-soft text-life-done">Done</Chip>
      <Chip className="bg-life-scheduled-soft text-life-scheduled">Scheduled</Chip>
      <Chip className="bg-life-recurring-soft text-life-recurring">Recurring</Chip>
      <Chip className="bg-life-accent-soft text-life-accent">Active</Chip>
      <Chip className="bg-life-card text-life-ink-2">Draft</Chip>
    </div>
  ),
};
