import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useIdentity } from "@/shell/identity";

import {
  getCodexServerAuth,
  getProviderSettings,
  importCodexServerAuth,
  putCodex,
  putOpenAI,
  putOpenRouter,
  putPreferredChat,
  putZAI,
  type ChatProvider,
  type CodexServerAuthStatus,
  type ProviderSettings,
} from "./providerApi";
import {
  DEFAULT_VOICE_PLAYBACK_SPEED,
  getRuntimeSettings,
  MAX_VOICE_PLAYBACK_SPEED,
  MIN_VOICE_PLAYBACK_SPEED,
  putRuntimeSetting,
} from "./runtimeSettingsApi";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; settings: ProviderSettings }
  | { kind: "error"; message: string };

type SaveStatus =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved" }
  | { kind: "error"; message: string };

const ZAI_ENDPOINT_OPTIONS = [
  { value: "coding-global", label: "coding (global)" },
  { value: "coding-cn", label: "coding (CN)" },
  { value: "global", label: "general (global)" },
  { value: "cn", label: "general (CN)" },
] as const;

const PROVIDER_LABELS: Record<ChatProvider, string> = {
  openai: "OpenAI",
  openrouter: "OpenRouter",
  zai: "Z.ai (GLM)",
  codex: "ChatGPT subscription (Codex)",
};

const DEFAULT_MODELS: Record<ChatProvider, string> = {
  openai: "gpt-5.1",
  openrouter: "openrouter/auto",
  zai: "glm-5.1",
  codex: "gpt-5.5",
};

const DEFAULT_OPENROUTER_TTS_MODEL = "canopylabs/orpheus-3b-0.1-ft";
const DEFAULT_OPENROUTER_TTS_VOICE = "tara";
const MIN_VAD_TIMEOUT_MS = 250;
const MAX_VAD_TIMEOUT_MS = 30000;
const DEFAULT_VAD_TIMEOUT_MS = "4000";
const DEFAULT_VOICE_PLAYBACK_SPEED_LABEL = String(DEFAULT_VOICE_PLAYBACK_SPEED);

type OpenRouterTtsModelOption = {
  value: string;
  label: string;
  voices: readonly string[];
};

const OPENROUTER_TTS_MODELS: readonly OpenRouterTtsModelOption[] = [
  {
    value: "canopylabs/orpheus-3b-0.1-ft",
    label: "Orpheus 3B",
    voices: ["tara", "leah", "jess", "leo", "dan", "mia", "zac"],
  },
  {
    value: "openai/gpt-4o-mini-tts-2025-12-15",
    label: "OpenAI GPT-4o mini TTS",
    voices: [
      "alloy",
      "ash",
      "ballad",
      "coral",
      "echo",
      "fable",
      "onyx",
      "nova",
      "sage",
      "shimmer",
      "verse",
      "marin",
      "cedar",
    ],
  },
  {
    value: "hexgrad/kokoro-82m",
    label: "Kokoro 82M",
    voices: [
      "af_bella",
      "af_nova",
      "af_heart",
      "af_sarah",
      "am_echo",
      "am_onyx",
      "bf_emma",
      "bm_fable",
    ],
  },
  {
    value: "google/gemini-3.1-flash-tts-preview",
    label: "Gemini 3.1 Flash TTS preview",
    voices: ["Zephyr", "Puck", "Charon", "Kore", "Aoede"],
  },
  {
    value: "mistralai/voxtral-mini-tts-2603",
    label: "Voxtral Mini TTS",
    voices: [
      "en_paul_neutral",
      "en_paul_cheerful",
      "en_paul_excited",
      "gb_oliver_neutral",
      "gb_oliver_cheerful",
      "gb_jane_sarcasm",
      "fr_marie_neutral",
    ],
  },
  {
    value: "sesame/csm-1b",
    label: "Sesame CSM 1B",
    voices: [
      "conversational_a",
      "conversational_b",
      "read_speech_a",
      "read_speech_b",
      "read_speech_c",
      "read_speech_d",
    ],
  },
  {
    value: "zyphra/zonos-v0.1-hybrid",
    label: "Zonos v0.1 hybrid",
    voices: [
      "american_female",
      "american_male",
      "british_female",
      "british_male",
      "random",
    ],
  },
  {
    value: "zyphra/zonos-v0.1-transformer",
    label: "Zonos v0.1 transformer",
    voices: [
      "american_female",
      "american_male",
      "british_female",
      "british_male",
      "random",
    ],
  },
];

const CUSTOM_SELECT_VALUE = "__custom__";

export function SettingsPanel() {
  const { refetch } = useIdentity();
  const [load, setLoad] = useState<LoadState>({ kind: "loading" });

  const reload = async () => {
    try {
      const settings = await getProviderSettings();
      setLoad({ kind: "ready", settings });
      refetch();
    } catch (e) {
      setLoad({ kind: "error", message: e instanceof Error ? e.message : String(e) });
    }
  };

  useEffect(() => {
    let cancelled = false;
    getProviderSettings()
      .then((settings) => {
        if (cancelled) return;
        setLoad({ kind: "ready", settings });
      })
      .catch((e) => {
        if (cancelled) return;
        setLoad({
          kind: "error",
          message: e instanceof Error ? e.message : String(e),
        });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (load.kind === "loading") {
    return (
      <div className="flex h-full items-center justify-center text-sm text-life-ink-3">
        Loading…
      </div>
    );
  }
  if (load.kind === "error") {
    return <div className="p-4 text-sm text-red-500">{load.message}</div>;
  }

  const s = load.settings;
  const configuredProviders = (
    ["openai", "openrouter", "zai", "codex"] as const
  ).filter((p) => s[p].configured);

  return (
    <div className="flex h-full flex-col overflow-y-auto p-4 gap-6">
      <header className="flex flex-col gap-1">
        <h2 className="text-sm font-semibold">Providers</h2>
        <p className="text-xs text-life-ink-3">
          Configure one or more providers. The agent uses your preferred chat provider
          (or falls through the list when unset). Voice transcription needs OpenRouter
          (Whisper); voice replies use OpenRouter when configured, otherwise the
          browser's built-in voice.
        </p>
      </header>

      <PreferredChatPicker
        current={s.preferred_chat_provider}
        configured={configuredProviders}
        onSave={async (next) => {
          await putPreferredChat(next);
          await reload();
        }}
      />

      <OpenAICard settings={s} onSaved={reload} />
      <OpenRouterCard settings={s} onSaved={reload} />
      <ZAICard settings={s} onSaved={reload} />
      <CodexCard settings={s} onSaved={reload} />
      <SetupDocsCard />
      <RuntimeSettingsCard />
    </div>
  );
}

// ── Preferred chat picker ────────────────────────────────────────

function PreferredChatPicker({
  current,
  configured,
  onSave,
}: {
  current: ChatProvider | null;
  configured: readonly ChatProvider[];
  onSave: (next: ChatProvider | null) => Promise<void>;
}) {
  const [save, setSave] = useState<SaveStatus>({ kind: "idle" });
  const [pending, setPending] = useState<ChatProvider | "auto">(current ?? "auto");

  useEffect(() => {
    setPending(current ?? "auto");
  }, [current]);

  const dirty = (current ?? "auto") !== pending;

  return (
    <section className="flex flex-col gap-2 rounded-md border border-life-line p-4">
      <h3 className="text-sm font-semibold">Preferred chat provider</h3>
      <p className="text-[11px] text-life-ink-3">
        Which configured provider the chat agent uses. "Auto" picks the first
        configured provider in this order: OpenAI, OpenRouter, Z.ai, Codex.
      </p>
      <div className="flex items-center gap-3">
        <Select
          value={pending}
          onValueChange={(v) => v && setPending(v as ChatProvider | "auto")}
        >
          <SelectTrigger className="w-full max-w-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="auto">Auto</SelectItem>
            {configured.map((p) => (
              <SelectItem key={p} value={p}>
                {PROVIDER_LABELS[p]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          type="button"
          aria-label="Save preferred chat provider"
          disabled={!dirty || save.kind === "saving"}
          onClick={async () => {
            setSave({ kind: "saving" });
            try {
              await onSave(pending === "auto" ? null : pending);
              setSave({ kind: "saved" });
            } catch (e) {
              setSave({
                kind: "error",
                message: e instanceof Error ? e.message : String(e),
              });
            }
          }}
        >
          {save.kind === "saving" ? "Saving…" : "Save"}
        </Button>
        {save.kind === "saved" && (
          <span className="text-xs text-green-600">Saved.</span>
        )}
        {save.kind === "error" && (
          <span className="text-xs text-red-500">{save.message}</span>
        )}
      </div>
    </section>
  );
}

// ── Per-provider cards ──────────────────────────────────────────

function ProviderCard({
  title,
  configured,
  onClear,
  onSave,
  saveDisabled,
  children,
}: {
  title: string;
  configured: boolean;
  onClear: () => Promise<void>;
  onSave: (e: FormEvent) => Promise<void>;
  saveDisabled: boolean;
  children: ReactNode;
}) {
  const [save, setSave] = useState<SaveStatus>({ kind: "idle" });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSave({ kind: "saving" });
    try {
      await onSave(e);
      setSave({ kind: "saved" });
    } catch (err) {
      setSave({
        kind: "error",
        message: err instanceof Error ? err.message : String(err),
      });
    }
  };

  const clear = async () => {
    setSave({ kind: "saving" });
    try {
      await onClear();
      setSave({ kind: "saved" });
    } catch (err) {
      setSave({
        kind: "error",
        message: err instanceof Error ? err.message : String(err),
      });
    }
  };

  return (
    <form
      onSubmit={submit}
      className="flex flex-col gap-3 rounded-md border border-life-line p-4"
    >
      <header className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">{title}</h3>
        <span
          className={`text-[11px] ${
            configured ? "text-green-600" : "text-life-ink-3"
          }`}
        >
          {configured ? "Configured" : "Not configured"}
        </span>
      </header>
      {children}
      <div className="flex items-center gap-3">
        <Button
          type="submit"
          aria-label={`Save ${title}`}
          disabled={save.kind === "saving" || saveDisabled}
        >
          {save.kind === "saving" ? "Saving…" : "Save"}
        </Button>
        {configured && (
          <Button
            type="button"
            variant="ghost"
            onClick={clear}
            disabled={save.kind === "saving"}
          >
            Clear
          </Button>
        )}
        {save.kind === "saved" && (
          <span className="text-xs text-green-600">Saved.</span>
        )}
        {save.kind === "error" && (
          <span className="text-xs text-red-500">{save.message}</span>
        )}
      </div>
    </form>
  );
}

function OpenAICard({
  settings,
  onSaved,
}: {
  settings: ProviderSettings;
  onSaved: () => Promise<void>;
}) {
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(settings.openai.chat_model ?? "");

  return (
    <ProviderCard
      title={PROVIDER_LABELS.openai}
      configured={settings.openai.configured}
      saveDisabled={!settings.openai.configured && !apiKey}
      onClear={async () => {
        await putOpenAI({ api_key: "" });
        setApiKey("");
        setModel("");
        await onSaved();
      }}
      onSave={async () => {
        await putOpenAI({
          api_key: apiKey || null,
          chat_model: model || null,
        });
        setApiKey("");
        await onSaved();
      }}
    >
      <FieldRow>
        <Label htmlFor="openai-key">API key</Label>
        <Input
          id="openai-key"
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={
            settings.openai.configured
              ? "•••••• (leave blank to keep current)"
              : "sk-…"
          }
          autoComplete="off"
        />
      </FieldRow>
      <FieldRow>
        <Label htmlFor="openai-model">Chat model</Label>
        <Input
          id="openai-model"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          placeholder={DEFAULT_MODELS.openai}
        />
      </FieldRow>
    </ProviderCard>
  );
}

function openRouterTtsModelOption(model: string) {
  return OPENROUTER_TTS_MODELS.find((option) => option.value === model);
}

function openRouterTtsVoiceOptions(model: string) {
  return (
    openRouterTtsModelOption(model)?.voices ??
    openRouterTtsModelOption(DEFAULT_OPENROUTER_TTS_MODEL)?.voices ??
    []
  );
}

function selectValueForCustomizableValue(
  value: string,
  options: readonly string[],
) {
  if (!value) return "";
  return options.includes(value) ? value : CUSTOM_SELECT_VALUE;
}

function OpenRouterTtsModelSelect({
  id,
  value,
  onChange,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const modelValues = OPENROUTER_TTS_MODELS.map((option) => option.value);
  const selectValue = selectValueForCustomizableValue(value, modelValues);
  const [custom, setCustom] = useState(selectValue === CUSTOM_SELECT_VALUE);

  useEffect(() => {
    if (value) setCustom(selectValue === CUSTOM_SELECT_VALUE);
  }, [selectValue, value]);

  return (
    <div className="flex flex-col gap-2">
      <Select
        value={selectValue}
        onValueChange={(next) => {
          if (!next) return;
          if (next === CUSTOM_SELECT_VALUE) {
            setCustom(true);
            onChange(openRouterTtsModelOption(value) ? "" : value);
            return;
          }
          setCustom(false);
          onChange(next);
        }}
      >
        <SelectTrigger id={id} aria-label="TTS model" className="w-full">
          <SelectValue placeholder={DEFAULT_OPENROUTER_TTS_MODEL} />
        </SelectTrigger>
        <SelectContent>
          {OPENROUTER_TTS_MODELS.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label} ({option.value})
            </SelectItem>
          ))}
          <SelectItem value={CUSTOM_SELECT_VALUE}>Custom…</SelectItem>
        </SelectContent>
      </Select>
      {custom ? (
        <Input
          aria-label="Custom TTS model"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={DEFAULT_OPENROUTER_TTS_MODEL}
        />
      ) : null}
    </div>
  );
}

function OpenRouterTtsVoiceSelect({
  id,
  model,
  value,
  onChange,
}: {
  id: string;
  model: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const voiceOptions = openRouterTtsVoiceOptions(model);
  const selectValue = selectValueForCustomizableValue(value, voiceOptions);
  const [custom, setCustom] = useState(selectValue === CUSTOM_SELECT_VALUE);

  useEffect(() => {
    if (value) setCustom(selectValue === CUSTOM_SELECT_VALUE);
  }, [selectValue, value]);

  return (
    <div className="flex flex-col gap-2">
      <Select
        value={selectValue}
        onValueChange={(next) => {
          if (!next) return;
          if (next === CUSTOM_SELECT_VALUE) {
            setCustom(true);
            onChange(voiceOptions.includes(value) ? "" : value);
            return;
          }
          setCustom(false);
          onChange(next);
        }}
      >
        <SelectTrigger id={id} aria-label="TTS voice" className="w-full">
          <SelectValue placeholder={DEFAULT_OPENROUTER_TTS_VOICE} />
        </SelectTrigger>
        <SelectContent>
          {voiceOptions.map((voice) => (
            <SelectItem key={voice} value={voice}>
              {voice}
            </SelectItem>
          ))}
          <SelectItem value={CUSTOM_SELECT_VALUE}>Custom…</SelectItem>
        </SelectContent>
      </Select>
      {custom ? (
        <Input
          aria-label="Custom TTS voice"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={DEFAULT_OPENROUTER_TTS_VOICE}
        />
      ) : null}
    </div>
  );
}

function OpenRouterCard({
  settings,
  onSaved,
}: {
  settings: ProviderSettings;
  onSaved: () => Promise<void>;
}) {
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(settings.openrouter.chat_model ?? "");
  const [ttsModel, setTtsModel] = useState(settings.openrouter.tts_model ?? "");
  const [ttsVoice, setTtsVoice] = useState(settings.openrouter.tts_voice ?? "");

  return (
    <ProviderCard
      title={PROVIDER_LABELS.openrouter}
      configured={settings.openrouter.configured}
      saveDisabled={!settings.openrouter.configured && !apiKey}
      onClear={async () => {
        await putOpenRouter({ api_key: "", tts_model: "", tts_voice: "" });
        setApiKey("");
        setModel("");
        setTtsModel("");
        setTtsVoice("");
        await onSaved();
      }}
      onSave={async () => {
        await putOpenRouter({
          api_key: apiKey || null,
          chat_model: model || null,
          tts_model: ttsModel || null,
          tts_voice: ttsVoice || null,
        });
        setApiKey("");
        await onSaved();
      }}
    >
      <p className="text-[11px] text-life-ink-3">
        Used for voice transcription (Whisper) and — when configured — voice replies.
      </p>
      <FieldRow>
        <Label htmlFor="or-key">API key</Label>
        <Input
          id="or-key"
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={
            settings.openrouter.configured
              ? "•••••• (leave blank to keep current)"
              : "sk-or-…"
          }
          autoComplete="off"
        />
      </FieldRow>
      <FieldRow>
        <Label htmlFor="or-model">Chat model</Label>
        <Input
          id="or-model"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          placeholder={DEFAULT_MODELS.openrouter}
        />
      </FieldRow>
      <FieldRow>
        <Label htmlFor="or-tts-model">TTS model</Label>
        <OpenRouterTtsModelSelect
          id="or-tts-model"
          value={ttsModel}
          onChange={(nextModel) => {
            setTtsModel(nextModel);
            const nextOption = openRouterTtsModelOption(nextModel);
            if (nextOption && !nextOption.voices.includes(ttsVoice)) {
              setTtsVoice(nextOption.voices[0] ?? "");
            }
          }}
        />
      </FieldRow>
      <FieldRow>
        <Label htmlFor="or-tts-voice">TTS voice</Label>
        <OpenRouterTtsVoiceSelect
          id="or-tts-voice"
          model={ttsModel}
          value={ttsVoice}
          onChange={setTtsVoice}
        />
      </FieldRow>
    </ProviderCard>
  );
}

function ZAICard({
  settings,
  onSaved,
}: {
  settings: ProviderSettings;
  onSaved: () => Promise<void>;
}) {
  const [apiKey, setApiKey] = useState("");
  const [endpoint, setEndpoint] = useState(
    settings.zai.endpoint ?? ZAI_ENDPOINT_OPTIONS[0].value,
  );
  const [model, setModel] = useState(settings.zai.chat_model ?? "");

  return (
    <ProviderCard
      title={PROVIDER_LABELS.zai}
      configured={settings.zai.configured}
      saveDisabled={!settings.zai.configured && !apiKey}
      onClear={async () => {
        await putZAI({ api_key: "", endpoint: "" });
        setApiKey("");
        setModel("");
        await onSaved();
      }}
      onSave={async () => {
        await putZAI({
          api_key: apiKey || null,
          endpoint,
          chat_model: model || null,
        });
        setApiKey("");
        await onSaved();
      }}
    >
      <FieldRow>
        <Label htmlFor="zai-key">API key</Label>
        <Input
          id="zai-key"
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={
            settings.zai.configured
              ? "•••••• (leave blank to keep current)"
              : "zai-…"
          }
          autoComplete="off"
        />
      </FieldRow>
      <FieldRow>
        <Label htmlFor="zai-endpoint">Endpoint</Label>
        <Select value={endpoint} onValueChange={(v) => v && setEndpoint(v)}>
          <SelectTrigger id="zai-endpoint" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ZAI_ENDPOINT_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FieldRow>
      <FieldRow>
        <Label htmlFor="zai-model">Chat model</Label>
        <Input
          id="zai-model"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          placeholder={DEFAULT_MODELS.zai}
        />
      </FieldRow>
    </ProviderCard>
  );
}

function CodexCard({
  settings,
  onSaved,
}: {
  settings: ProviderSettings;
  onSaved: () => Promise<void>;
}) {
  const [model, setModel] = useState(settings.codex.chat_model ?? "");
  const [status, setStatus] = useState<
    | { kind: "loading" }
    | { kind: "ready"; value: CodexServerAuthStatus }
    | { kind: "error"; message: string }
  >({ kind: "loading" });
  const [save, setSave] = useState<SaveStatus>({ kind: "idle" });
  const [serverAction, setServerAction] = useState<SaveStatus>({ kind: "idle" });

  const loadStatus = async () => {
    setStatus({ kind: "loading" });
    try {
      setStatus({ kind: "ready", value: await getCodexServerAuth() });
    } catch (e) {
      setStatus({ kind: "error", message: e instanceof Error ? e.message : String(e) });
    }
  };

  useEffect(() => {
    setModel(settings.codex.chat_model ?? "");
  }, [settings.codex.chat_model]);

  useEffect(() => {
    let cancelled = false;
    getCodexServerAuth()
      .then((value) => {
        if (!cancelled) setStatus({ kind: "ready", value });
      })
      .catch((e) => {
        if (!cancelled) {
          setStatus({
            kind: "error",
            message: e instanceof Error ? e.message : String(e),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const readyStatus = status.kind === "ready" ? status.value : null;

  const saveModel = async (e: FormEvent) => {
    e.preventDefault();
    setSave({ kind: "saving" });
    try {
      await putCodex({ chat_model: model || null });
      await onSaved();
      setSave({ kind: "saved" });
    } catch (err) {
      setSave({
        kind: "error",
        message: err instanceof Error ? err.message : String(err),
      });
    }
  };

  const clear = async () => {
    setSave({ kind: "saving" });
    try {
      await putCodex({ clear_auth: true });
      setModel("");
      await onSaved();
      await loadStatus();
      setSave({ kind: "saved" });
    } catch (err) {
      setSave({
        kind: "error",
        message: err instanceof Error ? err.message : String(err),
      });
    }
  };

  const importServerAuth = async () => {
    setServerAction({ kind: "saving" });
    try {
      await importCodexServerAuth();
      await onSaved();
      await loadStatus();
      setServerAction({ kind: "saved" });
    } catch (err) {
      setServerAction({
        kind: "error",
        message: err instanceof Error ? err.message : String(err),
      });
    }
  };

  return (
    <section className="flex flex-col gap-3 rounded-md border border-life-line p-4">
      <header className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">{PROVIDER_LABELS.codex}</h3>
        <span
          className={`text-[11px] ${
            settings.codex.configured ? "text-green-600" : "text-life-ink-3"
          }`}
        >
          {settings.codex.configured ? "Configured" : "Not configured"}
        </span>
      </header>
      <p className="text-[11px] text-life-ink-3">
        Sign in to Codex on this server as the app user, then import that server
        login here.
      </p>
      {status.kind === "ready" ? (
        <div className="flex flex-col gap-1 rounded-md bg-life-surface-2 p-3 text-[11px] text-life-ink-3">
          <StatusLine
            label="Codex CLI"
            value={status.value.codex_cli_installed ? "Installed" : "Missing"}
          />
          <StatusLine
            label="Auth file"
            value={status.value.auth_file_exists ? status.value.auth_file : "Not found"}
          />
          <StatusLine
            label="Server login"
            value={status.value.importable ? "Ready to import" : "Not ready"}
          />
          {status.value.plan_type ? (
            <StatusLine label="Plan" value={status.value.plan_type} />
          ) : null}
          {status.value.expires_at ? (
            <StatusLine
              label="Token expiry"
              value={new Date(status.value.expires_at).toLocaleString()}
            />
          ) : null}
          {status.value.error ? (
            <p className="text-red-500">{status.value.error}</p>
          ) : null}
        </div>
      ) : status.kind === "loading" ? (
        <p className="text-[11px] text-life-ink-3">Checking server Codex login…</p>
      ) : (
        <p className="text-[11px] text-red-500">{status.message}</p>
      )}
      {readyStatus ? (
        <div className="flex flex-col gap-2">
          <CommandBlock label="Login command" command={readyStatus.login_command} />
          <CommandBlock label="Status command" command={readyStatus.status_command} />
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          variant="ghost"
          onClick={loadStatus}
          disabled={status.kind === "loading" || serverAction.kind === "saving"}
        >
          Check server login
        </Button>
        <Button
          type="button"
          onClick={importServerAuth}
          disabled={!readyStatus?.importable || serverAction.kind === "saving"}
        >
          {serverAction.kind === "saving" ? "Importing…" : "Use server login"}
        </Button>
        {serverAction.kind === "saved" && (
          <span className="text-xs text-green-600">Imported.</span>
        )}
        {serverAction.kind === "error" && (
          <span className="text-xs text-red-500">{serverAction.message}</span>
        )}
      </div>
      <form onSubmit={saveModel} className="flex flex-col gap-3">
      <FieldRow>
        <Label htmlFor="codex-model">Chat model</Label>
        <Input
          id="codex-model"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          placeholder={DEFAULT_MODELS.codex}
        />
      </FieldRow>
        <div className="flex items-center gap-3">
          <Button type="submit" disabled={save.kind === "saving"}>
            {save.kind === "saving" ? "Saving…" : "Save"}
          </Button>
          {settings.codex.configured && (
            <Button
              type="button"
              variant="ghost"
              onClick={clear}
              disabled={save.kind === "saving"}
            >
              Clear
            </Button>
          )}
          {save.kind === "saved" && (
            <span className="text-xs text-green-600">Saved.</span>
          )}
          {save.kind === "error" && (
            <span className="text-xs text-red-500">{save.message}</span>
          )}
        </div>
      </form>
    </section>
  );
}

function StatusLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-2">
      <span className="text-life-ink-3">{label}</span>
      <span className="break-words text-life-ink-1">{value}</span>
    </div>
  );
}

function CommandBlock({ label, command }: { label: string; command: string }) {
  return (
    <div className="flex flex-col gap-1">
      <Label>{label}</Label>
      <code className="block rounded-md bg-life-surface-2 p-2 font-mono text-[11px] leading-relaxed text-life-ink-1 break-words">
        {command}
      </code>
    </div>
  );
}

function SetupDocsCard() {
  return (
    <section className="flex flex-col gap-2 rounded-md border border-life-line p-4">
      <h3 className="text-sm font-semibold">Setup docs</h3>
      <p className="text-[11px] text-life-ink-3">
        Push notifications and microphone access require HTTPS. If you do not own a
        domain, follow the Tailscale guide to give Life Assistant a stable HTTPS URL.
      </p>
      <a
        className="text-xs font-medium text-life-ink-2 underline underline-offset-2"
        href="/docs/https-no-domain.md"
        target="_blank"
        rel="noreferrer"
      >
        Open HTTPS setup guide
      </a>
    </section>
  );
}

function RuntimeSettingsCard() {
  const [load, setLoad] = useState<
    | { kind: "loading" }
    | { kind: "ready" }
    | { kind: "error"; message: string }
  >({ kind: "loading" });
  const [save, setSave] = useState<SaveStatus>({ kind: "idle" });
  const [braveApiKey, setBraveApiKey] = useState("");
  const [vadTimeoutMs, setVadTimeoutMs] = useState(DEFAULT_VAD_TIMEOUT_MS);
  const [voicePlaybackSpeed, setVoicePlaybackSpeed] = useState(
    DEFAULT_VOICE_PLAYBACK_SPEED_LABEL,
  );

  useEffect(() => {
    let cancelled = false;
    getRuntimeSettings()
      .then((settings) => {
        if (cancelled) return;
        setBraveApiKey(settings.brave_api_key ?? "");
        setVadTimeoutMs(settings.vad_timeout_ms || DEFAULT_VAD_TIMEOUT_MS);
        setVoicePlaybackSpeed(
          settings.voice_playback_speed || DEFAULT_VOICE_PLAYBACK_SPEED_LABEL,
        );
        setLoad({ kind: "ready" });
      })
      .catch((e) => {
        if (cancelled) return;
        setLoad({
          kind: "error",
          message: e instanceof Error ? e.message : String(e),
        });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSave({ kind: "saving" });
    const parsedVadTimeoutMs = Number.parseInt(vadTimeoutMs, 10);
    if (
      !Number.isFinite(parsedVadTimeoutMs) ||
      String(parsedVadTimeoutMs) !== vadTimeoutMs ||
      parsedVadTimeoutMs < MIN_VAD_TIMEOUT_MS ||
      parsedVadTimeoutMs > MAX_VAD_TIMEOUT_MS
    ) {
      setSave({
        kind: "error",
        message: `Voice silence timeout must be ${MIN_VAD_TIMEOUT_MS}-${MAX_VAD_TIMEOUT_MS}ms.`,
      });
      return;
    }
    const voicePlaybackSpeedInput = voicePlaybackSpeed.trim();
    const parsedVoicePlaybackSpeed = Number.parseFloat(voicePlaybackSpeedInput);
    if (
      !/^\d+(?:\.\d+)?$/.test(voicePlaybackSpeedInput) ||
      !Number.isFinite(parsedVoicePlaybackSpeed) ||
      parsedVoicePlaybackSpeed < MIN_VOICE_PLAYBACK_SPEED ||
      parsedVoicePlaybackSpeed > MAX_VOICE_PLAYBACK_SPEED
    ) {
      setSave({
        kind: "error",
        message: `Voice playback speed must be ${MIN_VOICE_PLAYBACK_SPEED}-${MAX_VOICE_PLAYBACK_SPEED}x.`,
      });
      return;
    }
    try {
      await putRuntimeSetting("brave_api_key", braveApiKey);
      await putRuntimeSetting("vad_timeout_ms", String(parsedVadTimeoutMs));
      await putRuntimeSetting(
        "voice_playback_speed",
        String(parsedVoicePlaybackSpeed),
      );
      setVoicePlaybackSpeed(String(parsedVoicePlaybackSpeed));
      setSave({ kind: "saved" });
    } catch (err) {
      setSave({
        kind: "error",
        message: err instanceof Error ? err.message : String(err),
      });
    }
  };

  return (
    <form
      onSubmit={onSubmit}
      className="flex flex-col gap-3 rounded-md border border-life-line p-4"
    >
      <header className="flex flex-col gap-1">
        <h3 className="text-sm font-semibold">Tools</h3>
        <p className="text-[11px] text-life-ink-3">
          DB-backed app settings. Visible to the assistant and stored as plaintext.
        </p>
      </header>
      {load.kind === "error" && (
        <p className="text-xs text-red-500">{load.message}</p>
      )}
      <FieldRow>
        <Label htmlFor="brave_api_key">Brave API key</Label>
        <Input
          id="brave_api_key"
          type="text"
          value={braveApiKey}
          onChange={(e) => setBraveApiKey(e.target.value)}
          placeholder={
            load.kind === "loading" ? "Loading…" : "Paste Brave Search API key"
          }
          autoComplete="off"
          disabled={load.kind === "loading"}
        />
        <p className="text-[11px] text-life-ink-3">
          Used by the assistant's <code className="font-mono">web_search</code>{" "}
          tool. Leave blank to disable web search.
        </p>
      </FieldRow>
      <FieldRow>
        <Label htmlFor="vad_timeout_ms">Voice silence timeout (ms)</Label>
        <Input
          id="vad_timeout_ms"
          type="number"
          min={MIN_VAD_TIMEOUT_MS}
          max={MAX_VAD_TIMEOUT_MS}
          step={250}
          value={vadTimeoutMs}
          onChange={(e) => setVadTimeoutMs(e.target.value)}
          placeholder={
            load.kind === "loading" ? "Loading…" : DEFAULT_VAD_TIMEOUT_MS
          }
          disabled={load.kind === "loading"}
        />
        <p className="text-[11px] text-life-ink-3">
          Voice mode submits after this much silence following speech. Default is{" "}
          {DEFAULT_VAD_TIMEOUT_MS}ms.
        </p>
      </FieldRow>
      <FieldRow>
        <Label htmlFor="voice_playback_speed">Voice playback speed</Label>
        <Input
          id="voice_playback_speed"
          type="number"
          min={MIN_VOICE_PLAYBACK_SPEED}
          max={MAX_VOICE_PLAYBACK_SPEED}
          step={0.05}
          value={voicePlaybackSpeed}
          onChange={(e) => setVoicePlaybackSpeed(e.target.value)}
          placeholder={
            load.kind === "loading" ? "Loading…" : DEFAULT_VOICE_PLAYBACK_SPEED_LABEL
          }
          disabled={load.kind === "loading"}
        />
        <p className="text-[11px] text-life-ink-3">
          Speed for generated voice replies and browser speech fallback. Default is{" "}
          {DEFAULT_VOICE_PLAYBACK_SPEED_LABEL}x.
        </p>
      </FieldRow>
      <div className="flex items-center gap-3">
        <Button
          type="submit"
          aria-label="Save tools settings"
          disabled={save.kind === "saving" || load.kind === "loading"}
        >
          {save.kind === "saving" ? "Saving…" : "Save"}
        </Button>
        {save.kind === "saved" && (
          <span className="text-xs text-green-600">Saved.</span>
        )}
        {save.kind === "error" && (
          <span className="text-xs text-red-500">{save.message}</span>
        )}
      </div>
    </form>
  );
}

function FieldRow({ children }: { children: ReactNode }) {
  return <div className="flex flex-col gap-1.5">{children}</div>;
}
