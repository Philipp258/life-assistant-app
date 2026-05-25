import type { Meta, StoryObj } from "@storybook/react-vite";
import { BrainIcon, PlusIcon, XIcon } from "lucide-react";

import { IconButton } from "./IconButton";

const meta = {
  title: "Shell/IconButton",
  component: IconButton,
  parameters: {
    layout: "centered",
  },
  tags: ["autodocs"],
  argTypes: {
    active: { control: "boolean" },
    disabled: { control: "boolean" },
  },
  args: {
    "aria-label": "Add",
    children: <PlusIcon className="size-4" />,
    active: false,
  },
} satisfies Meta<typeof IconButton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Active: Story = {
  args: { active: true },
};

export const Disabled: Story = {
  args: { disabled: true },
};

export const Close: Story = {
  args: {
    "aria-label": "Close",
    children: <XIcon className="size-4" />,
  },
};

export const Brain: Story = {
  args: {
    "aria-label": "Reasoning",
    children: <BrainIcon className="size-4" />,
  },
};

export const States: Story = {
  render: () => (
    <div className="flex items-center gap-3">
      <IconButton aria-label="Add">
        <PlusIcon className="size-4" />
      </IconButton>
      <IconButton aria-label="Add" active>
        <PlusIcon className="size-4" />
      </IconButton>
      <IconButton aria-label="Add" disabled>
        <PlusIcon className="size-4" />
      </IconButton>
    </div>
  ),
};
