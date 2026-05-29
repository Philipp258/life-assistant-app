import type { Meta, StoryObj } from "@storybook/react-vite";
import {
  Check,
  KeyRound,
  Mic,
  RefreshCw,
  TerminalSquare,
} from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type ProviderId = "codex" | "openrouter" | "openai" | "zai";

type ProviderOption = {
  id: ProviderId;
  name: string;
  shortName: string;
  detail: string;
  model: string;
  credential: "server-login" | "api-key";
};

const PROVIDERS: ProviderOption[] = [
  {
    id: "codex",
    name: "ChatGPT subscription",
    shortName: "ChatGPT",
    detail: "Use Codex server login",
    model: "gpt-5.5",
    credential: "server-login",
  },
  {
    id: "openrouter",
    name: "OpenRouter",
    shortName: "OpenRouter",
    detail: "Use an OpenRouter API key",
    model: "openrouter/auto",
    credential: "api-key",
  },
  {
    id: "openai",
    name: "OpenAI",
    shortName: "OpenAI",
    detail: "Use an OpenAI API key",
    model: "gpt-5.1",
    credential: "api-key",
  },
  {
    id: "zai",
    name: "Z.ai",
    shortName: "Z.ai",
    detail: "Use a Z.ai API key",
    model: "glm-5.1",
    credential: "api-key",
  },
];

const meta = {
  title: "Onboarding/Provider Setup Exploration",
  parameters: {
    layout: "centered",
  },
  decorators: [
    (Story) => (
      <div className="w-[390px] max-w-[100vw] bg-life-bg text-life-ink">
        <Story />
      </div>
    ),
  ],
} satisfies Meta;

export default meta;
type Story = StoryObj<typeof meta>;

function PhoneFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto flex h-[760px] w-full max-w-[390px] flex-col overflow-hidden border border-life-line bg-life-bg">
      {children}
    </div>
  );
}

function SetupHeader({
  title = "Connect your assistant",
  body = "Choose the provider your assistant should use for chat.",
}: {
  title?: string;
  body?: string;
}) {
  return (
    <header className="border-b border-life-line bg-life-bg px-4 py-4">
      <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-life-ink-3">
        Setup
      </p>
      <h1 className="mt-1 text-lg font-semibold">{title}</h1>
      <p className="mt-1 text-sm text-life-ink-3">{body}</p>
    </header>
  );
}

function ProviderIcon({ provider }: { provider: ProviderOption }) {
  return provider.credential === "server-login" ? (
    <TerminalSquare className="size-3.5" />
  ) : (
    <KeyRound className="size-3.5" />
  );
}

function CompactProviderRow({
  provider,
  selected,
  onSelect,
}: {
  provider: ProviderOption;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      className={`flex min-h-12 items-center gap-2.5 rounded-md border px-3 py-2 text-left transition-colors ${
        selected
          ? "border-life-ink-1 bg-life-surface-2"
          : "border-life-line bg-life-bg hover:bg-life-surface-2"
      }`}
    >
      <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-life-card">
        <ProviderIcon provider={provider} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold">{provider.name}</span>
        <span className="block truncate text-[11px] text-life-ink-3">
          {provider.detail}
        </span>
      </span>
      {selected ? <Check className="size-3.5 shrink-0" /> : null}
    </button>
  );
}

function ProviderPill({
  provider,
  selected,
  onSelect,
}: {
  provider: ProviderOption;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      className={`inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full border px-3 text-xs font-medium ${
        selected
          ? "border-life-ink-1 bg-life-ink-1 text-white"
          : "border-life-line bg-life-bg text-life-ink-2"
      }`}
    >
      <ProviderIcon provider={provider} />
      {provider.shortName}
    </button>
  );
}

function ProviderForm({
  provider,
  actionLabel = "Continue",
  onContinue,
}: {
  provider: ProviderOption;
  actionLabel?: string;
  onContinue?: () => void;
}) {
  return (
    <section className="flex flex-col gap-3 rounded-md border border-life-line p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">{provider.name}</h2>
        <span className="text-[11px] text-life-ink-3">Selected</span>
      </div>

      {provider.credential === "server-login" ? (
        <div className="flex flex-col gap-2 rounded-md bg-life-surface-2 p-3">
          <div className="flex items-center justify-between gap-3 text-[11px]">
            <span className="text-life-ink-3">Server login</span>
            <span className="font-medium text-life-ink-1">Not ready</span>
          </div>
          <code className="block break-words rounded-md bg-life-bg p-2 font-mono text-[11px] leading-relaxed">
            env HOME=/root codex login --device-auth
          </code>
          <Button type="button" variant="outline" size="sm">
            <RefreshCw className="size-3.5" />
            Check login
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-1">
          <Label htmlFor={`key-${provider.id}`}>API key</Label>
          <Input
            id={`key-${provider.id}`}
            type="password"
            placeholder={provider.id === "zai" ? "zai-..." : "sk-..."}
          />
        </div>
      )}

      <div className="flex flex-col gap-1">
        <Label htmlFor={`model-${provider.id}`}>Chat model</Label>
        <Input id={`model-${provider.id}`} value={provider.model} readOnly />
      </div>

      <Button
        type="button"
        disabled={provider.credential === "server-login"}
        onClick={onContinue}
      >
        {actionLabel}
      </Button>
    </section>
  );
}

function actionLabelFor(provider: ProviderOption) {
  return `Use ${provider.shortName}`;
}

function VoiceStepPrototype({
  chatProvider,
  onBack,
}: {
  chatProvider: ProviderOption;
  onBack: () => void;
}) {
  const openRouterChat = chatProvider.id === "openrouter";

  return (
    <PhoneFrame>
      <SetupHeader
        title="Add voice?"
        body="Voice is optional. You can skip this and still use text chat."
      />
      <main className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
        <section className="flex flex-col gap-3 rounded-md border border-life-line p-4">
          <div className="flex items-start gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-life-surface-2">
              <Mic className="size-4" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-sm font-semibold">OpenRouter voice</h2>
              <p className="text-xs text-life-ink-3">
                Microphone transcription and hosted voice replies use OpenRouter.
              </p>
            </div>
          </div>

          {openRouterChat ? (
            <div className="rounded-md bg-life-surface-2 p-3 text-xs text-life-ink-3">
              OpenRouter was selected for chat, so the same key can enable voice.
            </div>
          ) : (
            <div className="flex flex-col gap-1">
              <Label htmlFor="voice-key">OpenRouter API key</Label>
              <Input id="voice-key" type="password" placeholder="sk-or-..." />
            </div>
          )}

          <div className="flex flex-col gap-2">
            <Button type="button">
              {openRouterChat ? "Enable voice" : "Set up voice"}
            </Button>
            <Button type="button" variant="outline">
              Skip voice
            </Button>
            <Button type="button" variant="ghost" onClick={onBack}>
              Back to chat
            </Button>
          </div>
        </section>
      </main>
    </PhoneFrame>
  );
}

function CompactRowsPrototype() {
  const [selected, setSelected] = useState<ProviderId>("codex");
  const [step, setStep] = useState<"chat" | "voice">("chat");
  const provider = PROVIDERS.find((item) => item.id === selected) ?? PROVIDERS[0];

  if (step === "voice") {
    return <VoiceStepPrototype chatProvider={provider} onBack={() => setStep("chat")} />;
  }

  return (
    <PhoneFrame>
      <SetupHeader body="Compact rows keep every chat provider visible without turning setup into a menu page." />
      <main className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
        <section className="grid gap-1.5">
          {PROVIDERS.map((item) => (
            <CompactProviderRow
              key={item.id}
              provider={item}
              selected={item.id === selected}
              onSelect={() => setSelected(item.id)}
            />
          ))}
        </section>
        <ProviderForm
          provider={provider}
          actionLabel={actionLabelFor(provider)}
          onContinue={() => setStep("voice")}
        />
      </main>
    </PhoneFrame>
  );
}

function PillRailPrototype() {
  const [selected, setSelected] = useState<ProviderId>("codex");
  const [step, setStep] = useState<"chat" | "voice">("chat");
  const provider = PROVIDERS.find((item) => item.id === selected) ?? PROVIDERS[0];

  if (step === "voice") {
    return <VoiceStepPrototype chatProvider={provider} onBack={() => setStep("chat")} />;
  }

  return (
    <PhoneFrame>
      <SetupHeader
        body="A single horizontal chat-provider rail is compact, but still keeps alternatives visible."
      />
      <main className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
        <section
          aria-label="Chat provider"
          className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1"
        >
          {PROVIDERS.map((item) => (
            <ProviderPill
              key={item.id}
              provider={item}
              selected={item.id === selected}
              onSelect={() => setSelected(item.id)}
            />
          ))}
        </section>

        <ProviderForm
          provider={provider}
          actionLabel={actionLabelFor(provider)}
          onContinue={() => setStep("voice")}
        />
      </main>
    </PhoneFrame>
  );
}

function DropdownPrototype() {
  const [selected, setSelected] = useState<ProviderId>("codex");
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<"chat" | "voice">("chat");
  const provider = PROVIDERS.find((item) => item.id === selected) ?? PROVIDERS[0];

  if (step === "voice") {
    return <VoiceStepPrototype chatProvider={provider} onBack={() => setStep("chat")} />;
  }

  return (
    <PhoneFrame>
      <SetupHeader body="A dropdown-style chat picker is shortest by default, with all options one tap away." />
      <main className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
        <section className="flex flex-col gap-2">
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
            className="flex min-h-12 items-center justify-between rounded-md border border-life-line px-3 py-2 text-left"
          >
            <span className="flex min-w-0 items-center gap-2.5">
              <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-life-card">
                <ProviderIcon provider={provider} />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold">{provider.name}</span>
                <span className="block truncate text-[11px] text-life-ink-3">
                  {provider.detail}
                </span>
              </span>
            </span>
            <span className="text-xs font-medium text-life-ink-3">
              {open ? "Close" : "Change"}
            </span>
          </button>
          {open ? (
            <div className="grid gap-1 rounded-md border border-life-line p-1">
              {PROVIDERS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => {
                    setSelected(item.id);
                    setOpen(false);
                  }}
                  className="flex min-h-10 items-center justify-between rounded-[4px] px-2 text-left text-sm hover:bg-life-surface-2"
                >
                  <span>{item.name}</span>
                  {item.id === selected ? <Check className="size-3.5" /> : null}
                </button>
              ))}
            </div>
          ) : null}
        </section>

        <ProviderForm
          provider={provider}
          actionLabel={actionLabelFor(provider)}
          onContinue={() => setStep("voice")}
        />
      </main>
    </PhoneFrame>
  );
}

function InlineAccordionPrototype() {
  const [selected, setSelected] = useState<ProviderId>("codex");
  const [step, setStep] = useState<"chat" | "voice">("chat");
  const provider = PROVIDERS.find((item) => item.id === selected) ?? PROVIDERS[0];

  if (step === "voice") {
    return <VoiceStepPrototype chatProvider={provider} onBack={() => setStep("chat")} />;
  }

  return (
    <PhoneFrame>
      <SetupHeader body="Rows stay dense, and the active provider opens in place." />
      <main className="flex flex-1 flex-col gap-3 overflow-y-auto p-4">
        <section className="overflow-hidden rounded-md border border-life-line">
          {PROVIDERS.map((item) => (
            <div key={item.id} className="border-b border-life-line last:border-b-0">
              <button
                type="button"
                aria-expanded={selected === item.id}
                onClick={() => setSelected(item.id)}
                className="flex min-h-11 w-full items-center justify-between px-3 py-2 text-left"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-life-card">
                    <ProviderIcon provider={item} />
                  </span>
                  <span className="truncate text-sm font-medium">{item.name}</span>
                </span>
                {selected === item.id ? <Check className="size-3.5" /> : null}
              </button>
              {selected === item.id ? (
                <div className="border-t border-life-line bg-life-bg p-3">
                  <ProviderForm
                    provider={provider}
                    actionLabel={actionLabelFor(provider)}
                    onContinue={() => setStep("voice")}
                  />
                </div>
              ) : null}
            </div>
          ))}
        </section>
      </main>
    </PhoneFrame>
  );
}

function ComparisonBoard() {
  return (
    <div className="grid gap-6 p-4 lg:grid-cols-2">
      <div>
        <h2 className="mb-2 text-sm font-semibold">A. Compact rows</h2>
        <CompactRowsPrototype />
      </div>
      <div>
        <h2 className="mb-2 text-sm font-semibold">B. Pill rail</h2>
        <PillRailPrototype />
      </div>
      <div>
        <h2 className="mb-2 text-sm font-semibold">C. Dropdown</h2>
        <DropdownPrototype />
      </div>
      <div>
        <h2 className="mb-2 text-sm font-semibold">D. Inline accordion</h2>
        <InlineAccordionPrototype />
      </div>
    </div>
  );
}

export const CompactRows: Story = {
  render: () => <CompactRowsPrototype />,
};

export const PillRail: Story = {
  render: () => <PillRailPrototype />,
};

export const Dropdown: Story = {
  render: () => <DropdownPrototype />,
};

export const InlineAccordion: Story = {
  render: () => <InlineAccordionPrototype />,
};

export const EqualChoices: Story = {
  render: () => <CompactRowsPrototype />,
};

export const RecommendedDefault: Story = {
  render: () => <DropdownPrototype />,
};

export const Checklist: Story = {
  render: () => <InlineAccordionPrototype />,
};

export const Segmented: Story = {
  name: "Pill rail",
  render: () => <PillRailPrototype />,
};

export const CompareAll: Story = {
  parameters: {
    layout: "fullscreen",
  },
  render: () => <ComparisonBoard />,
};
