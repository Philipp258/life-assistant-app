import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProviderSetupStepper, SettingsPanel } from "./SettingsPanel";
import type { CodexServerAuthStatus, OpenRouterBlock } from "./providerApi";
import type { RuntimeSettings } from "./runtimeSettingsApi";

const fetchMock = vi.fn();
const refetchMock = vi.fn();

vi.mock("@/shell/identity", () => ({
  useIdentity: () => ({ refetch: refetchMock }),
}));

type FetchInit = RequestInit & { method?: string };

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const defaultProviderSettings = {
  preferred_chat_provider: "zai",
  openai: { configured: false, chat_model: null },
  openrouter: { configured: false, chat_model: null, tts_model: null, tts_voice: null },
  zai: { configured: true, endpoint: "coding-global", chat_model: "glm-5.1" },
  codex: { configured: false, chat_model: null },
};

const defaultCodexServerAuth: CodexServerAuthStatus = {
  codex_cli_installed: true,
  auth_file: "/root/.codex/auth.json",
  auth_file_exists: true,
  importable: true,
  configured: false,
  expires_at: "2026-05-25T12:00:00Z",
  plan_type: "plus",
  error: null,
  login_command: "env HOME=/root codex login --device-auth",
  status_command: "env HOME=/root codex login status",
};

function setupFetch(
  options: {
    runtime?: Partial<RuntimeSettings>;
    provider?: Record<string, unknown>;
    codexServerAuth?: CodexServerAuthStatus;
    importProvider?: Record<string, unknown>;
  } = {},
) {
  const provider = options.provider ?? defaultProviderSettings;
  const importProvider = options.importProvider ?? {
    ...defaultProviderSettings,
    codex: { configured: true, chat_model: null },
  };
  const codexServerAuth = options.codexServerAuth ?? defaultCodexServerAuth;
  const runtime = {
    brave_api_key: "",
    vad_timeout_ms: "",
    voice_playback_speed: "",
    ...options.runtime,
  };

  fetchMock.mockImplementation((input: string, init?: FetchInit) => {
    const method = init?.method ?? "GET";
    if (input === "/api/settings/providers" && method === "GET") {
      return Promise.resolve(jsonResponse(provider));
    }
    if (
      input === "/api/settings/providers/codex/server-auth" &&
      method === "GET"
    ) {
      return Promise.resolve(jsonResponse(codexServerAuth));
    }
    if (
      input === "/api/settings/providers/codex/import-server-auth" &&
      method === "POST"
    ) {
      return Promise.resolve(jsonResponse(importProvider));
    }
    if (input.startsWith("/api/settings/providers/") && method === "PUT") {
      return Promise.resolve(jsonResponse(provider));
    }
    if (input === "/api/settings/runtime" && method === "GET") {
      return Promise.resolve(jsonResponse(runtime));
    }
    if (input.startsWith("/api/settings/runtime/") && method === "PUT") {
      const key = input.split("/").pop() ?? "";
      const body = JSON.parse(init?.body as string) as { value: string };
      return Promise.resolve(jsonResponse({ key, value: body.value }));
    }
    return Promise.resolve(jsonResponse({ detail: "unmocked" }, 500));
  });
}

function toolsForm() {
  const input = screen.getByLabelText(/brave api key/i);
  const form = input.closest("form");
  if (!form) throw new Error("Brave API key input is not inside a form");
  return form;
}

beforeEach(() => {
  fetchMock.mockReset();
  refetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SettingsPanel — Brave API key", () => {
  it("loads the stored Brave API key into the input", async () => {
    setupFetch({
      runtime: { brave_api_key: "loaded-brave-key", vad_timeout_ms: "" },
    });
    render(<SettingsPanel />);

    const input = (await screen.findByLabelText(
      /brave api key/i,
    )) as HTMLInputElement;
    await waitFor(() => expect(input.value).toBe("loaded-brave-key"));
  });

  it("shows an empty Brave key field when nothing is configured", async () => {
    setupFetch({ runtime: { brave_api_key: "", vad_timeout_ms: "" } });
    render(<SettingsPanel />);

    const input = (await screen.findByLabelText(
      /brave api key/i,
    )) as HTMLInputElement;
    await waitFor(() => expect(input).not.toBeDisabled());
    expect(input.value).toBe("");
  });

  it("PUTs the edited Brave key on save", async () => {
    setupFetch({ runtime: { brave_api_key: "", vad_timeout_ms: "" } });
    render(<SettingsPanel />);

    const input = await screen.findByLabelText(/brave api key/i);
    await waitFor(() => expect(input).not.toBeDisabled());
    await userEvent.type(input, "new-brave-key");
    await userEvent.click(
      within(toolsForm()).getByRole("button", { name: /save/i }),
    );

    await waitFor(() => {
      const putCalls = fetchMock.mock.calls.filter(
        ([url, init]) =>
          url === "/api/settings/runtime/brave_api_key" &&
          (init as FetchInit | undefined)?.method === "PUT",
      );
      expect(putCalls).toHaveLength(1);
      expect(JSON.parse(putCalls[0][1].body as string)).toEqual({
        value: "new-brave-key",
      });
    });
  });

  it("PUTs an empty value when the user clears the Brave key", async () => {
    setupFetch({ runtime: { brave_api_key: "existing-key", vad_timeout_ms: "" } });
    render(<SettingsPanel />);

    const input = (await screen.findByLabelText(
      /brave api key/i,
    )) as HTMLInputElement;
    await waitFor(() => expect(input.value).toBe("existing-key"));
    await userEvent.clear(input);
    await userEvent.click(within(toolsForm()).getByRole("button", { name: /save/i }));

    await waitFor(() => {
      const putCalls = fetchMock.mock.calls.filter(
        ([url, init]) =>
          url === "/api/settings/runtime/brave_api_key" &&
          (init as FetchInit | undefined)?.method === "PUT",
      );
      expect(putCalls).toHaveLength(1);
      expect(JSON.parse(putCalls[0][1].body as string)).toEqual({
        value: "",
      });
    });
  });

  it("loads and saves the voice silence timeout", async () => {
    setupFetch({ runtime: { brave_api_key: "", vad_timeout_ms: "1750" } });
    render(<SettingsPanel />);

    const input = (await screen.findByLabelText(
      /voice silence timeout/i,
    )) as HTMLInputElement;
    await waitFor(() => expect(input.value).toBe("1750"));
    await userEvent.clear(input);
    await userEvent.type(input, "2250");
    await userEvent.click(within(toolsForm()).getByRole("button", { name: /save/i }));

    await waitFor(() => {
      const putCalls = fetchMock.mock.calls.filter(
        ([url, init]) =>
          url === "/api/settings/runtime/vad_timeout_ms" &&
          (init as FetchInit | undefined)?.method === "PUT",
      );
      expect(putCalls).toHaveLength(1);
      expect(JSON.parse(putCalls[0][1].body as string)).toEqual({
        value: "2250",
      });
    });
  });

  it("loads and saves the voice playback speed", async () => {
    setupFetch({ runtime: { voice_playback_speed: "1.25" } });
    render(<SettingsPanel />);

    const input = (await screen.findByLabelText(
      /voice playback speed/i,
    )) as HTMLInputElement;
    await waitFor(() => expect(input.value).toBe("1.25"));
    await userEvent.clear(input);
    await userEvent.type(input, "1.15");
    await userEvent.click(within(toolsForm()).getByRole("button", { name: /save/i }));

    await waitFor(() => {
      const putCalls = fetchMock.mock.calls.filter(
        ([url, init]) =>
          url === "/api/settings/runtime/voice_playback_speed" &&
          (init as FetchInit | undefined)?.method === "PUT",
      );
      expect(putCalls).toHaveLength(1);
      expect(JSON.parse(putCalls[0][1].body as string)).toEqual({
        value: "1.15",
      });
    });
  });
});


describe("SettingsPanel — provider save buttons", () => {
  function codexForm() {
    const input = screen.getByLabelText(/chat model/i, {
      selector: "#codex-model",
    });
    const form = input.closest("form");
    if (!form) throw new Error("Provider input is not inside a form");
    return form;
  }

  it("shows Codex server login status and imports it", async () => {
    setupFetch({
      provider: {
        ...defaultProviderSettings,
        codex: { configured: false, chat_model: null },
      },
    });
    render(<SettingsPanel />);

    expect(await screen.findByText(/codex login --device-auth/i)).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: /use server login/i }),
    );

    await waitFor(() => {
      const importCalls = fetchMock.mock.calls.filter(
        ([url, init]) =>
          url === "/api/settings/providers/codex/import-server-auth" &&
          (init as FetchInit | undefined)?.method === "POST",
      );
      expect(importCalls).toHaveLength(1);
    });
  });

  it("shows refresh wording when Codex is configured and a server login is available", async () => {
    setupFetch({
      provider: {
        ...defaultProviderSettings,
        codex: { configured: true, chat_model: null },
      },
      codexServerAuth: {
        ...defaultCodexServerAuth,
        configured: true,
        importable: true,
      },
    });
    render(<SettingsPanel />);

    expect(await screen.findByText("Available for refresh")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /refresh server login/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Ready to import")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /use server login/i }),
    ).not.toBeInTheDocument();
  });

  it("PUTs Codex model when the Codex Save button is clicked", async () => {
    setupFetch({
      provider: {
        ...defaultProviderSettings,
        codex: { configured: false, chat_model: null },
      },
    });
    render(<SettingsPanel />);

    await screen.findByLabelText(/chat model/i, { selector: "#codex-model" });
    await userEvent.type(
      screen.getByLabelText(/chat model/i, { selector: "#codex-model" }),
      "gpt-5.5",
    );
    await userEvent.click(
      within(codexForm()).getByRole("button", {
        name: /save/i,
      }),
    );

    await waitFor(() => {
      const putCalls = fetchMock.mock.calls.filter(
        ([url, init]) =>
          url === "/api/settings/providers/codex" &&
          (init as FetchInit | undefined)?.method === "PUT",
      );
      expect(putCalls).toHaveLength(1);
      expect(JSON.parse(putCalls[0][1].body as string)).toEqual({
        chat_model: "gpt-5.5",
      });
    });
  });

  it("clears Codex auth explicitly", async () => {
    setupFetch({
      provider: {
        ...defaultProviderSettings,
        codex: { configured: true, chat_model: "gpt-5.5" },
      },
    });
    render(<SettingsPanel />);

    await screen.findByLabelText(/chat model/i, { selector: "#codex-model" });
    await userEvent.click(
      within(codexForm()).getByRole("button", {
        name: /clear/i,
      }),
    );

    await waitFor(() => {
      const putCalls = fetchMock.mock.calls.filter(
        ([url, init]) =>
          url === "/api/settings/providers/codex" &&
          (init as FetchInit | undefined)?.method === "PUT",
      );
      expect(putCalls).toHaveLength(1);
      expect(JSON.parse(putCalls[0][1].body as string)).toEqual({
        clear_auth: true,
      });
    });
  });

  it("shows all chat providers as peers without an advanced provider drawer", async () => {
    setupFetch();
    render(<SettingsPanel />);

    expect(
      await screen.findByRole("heading", {
        name: /chatgpt subscription/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "OpenRouter" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "OpenAI" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /z\.ai/i })).toBeInTheDocument();
    expect(screen.queryByText(/advanced chat providers/i)).not.toBeInTheDocument();
  });
});

describe("ProviderSetupStepper", () => {
  it("starts with peer chat-provider choices and pre-fills gpt-5.5", async () => {
    setupFetch({
      provider: {
        ...defaultProviderSettings,
        openai: { configured: false, chat_model: null },
        openrouter: { configured: false, chat_model: null, tts_model: null, tts_voice: null },
        zai: { configured: false, endpoint: "coding-global", chat_model: null },
        codex: { configured: false, chat_model: null },
      },
    });

    render(<ProviderSetupStepper />);

    expect(await screen.findByRole("heading", { name: /choose chat/i })).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: /chatgpt subscription best default/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /openrouter api key/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /openai api key/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /z\.ai api key/i })).toBeInTheDocument();
    expect(
      (screen.getByLabelText(/chat model/i, {
        selector: "#setup-codex-model",
      }) as HTMLInputElement).value,
    ).toBe("gpt-5.5");
    expect(document.querySelector("#setup-openrouter-key")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /openrouter api key/i }));

    expect(document.querySelector("#setup-codex-model")).not.toBeInTheDocument();
    expect(
      (screen.getByLabelText(/chat model/i, {
        selector: "#setup-openrouter-model",
      }) as HTMLInputElement).value,
    ).toBe("openrouter/auto");
    expect(document.querySelector("#setup-openrouter-key")).toBeInTheDocument();
    expect(screen.queryByText(/other chat providers/i)).not.toBeInTheDocument();
  });

  it("imports Codex, saves the visible default model, and pins chat to Codex", async () => {
    setupFetch({
      provider: {
        ...defaultProviderSettings,
        zai: { configured: false, endpoint: "coding-global", chat_model: null },
        codex: { configured: false, chat_model: null },
      },
    });

    render(<ProviderSetupStepper />);

    await screen.findByDisplayValue("gpt-5.5");
    await userEvent.click(
      screen.getByRole("button", { name: /use chatgpt subscription/i }),
    );

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            url === "/api/settings/providers/codex/import-server-auth" &&
            (init as FetchInit | undefined)?.method === "POST",
        ),
      ).toBe(true);
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            url === "/api/settings/providers/codex" &&
            (init as FetchInit | undefined)?.method === "PUT" &&
            JSON.parse((init as FetchInit).body as string).chat_model === "gpt-5.5",
        ),
      ).toBe(true);
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            url === "/api/settings/providers/preferred-chat" &&
            (init as FetchInit | undefined)?.method === "PUT" &&
            JSON.parse((init as FetchInit).body as string).preferred_chat_provider ===
              "codex",
        ),
      ).toBe(true);
    });
    expect(await screen.findByRole("heading", { name: /voice is optional/i })).toBeInTheDocument();
  });

  it("configures OpenRouter chat and finishes without showing the voice step", async () => {
    setupFetch({
      provider: {
        ...defaultProviderSettings,
        openrouter: { configured: false, chat_model: null, tts_model: null, tts_voice: null },
        zai: { configured: false, endpoint: "coding-global", chat_model: null },
        codex: { configured: false, chat_model: null },
      },
    });

    render(<ProviderSetupStepper />);

    await userEvent.click(await screen.findByRole("button", { name: /openrouter api key/i }));
    const key = screen.getByLabelText(/api key/i, {
      selector: "#setup-openrouter-key",
    });
    await userEvent.type(key, "sk-or-test");
    await userEvent.click(screen.getByRole("button", { name: /use openrouter for chat/i }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            url === "/api/settings/providers/openrouter" &&
            (init as FetchInit | undefined)?.method === "PUT" &&
            JSON.parse((init as FetchInit).body as string).chat_model ===
              "openrouter/auto",
        ),
      ).toBe(true);
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            url === "/api/settings/providers/preferred-chat" &&
            (init as FetchInit | undefined)?.method === "PUT" &&
            JSON.parse((init as FetchInit).body as string).preferred_chat_provider ===
              "openrouter",
        ),
      ).toBe(true);
      expect(refetchMock).toHaveBeenCalled();
    });
    expect(screen.queryByRole("heading", { name: /voice is optional/i })).not.toBeInTheDocument();
  });

  it("configures OpenAI chat and advances to optional voice", async () => {
    setupFetch({
      provider: {
        ...defaultProviderSettings,
        openai: { configured: false, chat_model: null },
        openrouter: { configured: false, chat_model: null, tts_model: null, tts_voice: null },
        zai: { configured: false, endpoint: "coding-global", chat_model: null },
        codex: { configured: false, chat_model: null },
      },
    });

    render(<ProviderSetupStepper />);

    await userEvent.click(await screen.findByRole("button", { name: /openai api key/i }));
    expect((screen.getByLabelText(/chat model/i) as HTMLInputElement).value).toBe("gpt-5.1");
    await userEvent.type(screen.getByLabelText(/api key/i), "sk-test");
    await userEvent.click(screen.getByRole("button", { name: /use openai/i }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            url === "/api/settings/providers/openai" &&
            (init as FetchInit | undefined)?.method === "PUT" &&
            JSON.parse((init as FetchInit).body as string).chat_model === "gpt-5.1",
        ),
      ).toBe(true);
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            url === "/api/settings/providers/preferred-chat" &&
            (init as FetchInit | undefined)?.method === "PUT" &&
            JSON.parse((init as FetchInit).body as string).preferred_chat_provider ===
              "openai",
        ),
      ).toBe(true);
    });
    expect(await screen.findByRole("heading", { name: /voice is optional/i })).toBeInTheDocument();
  });

  it("configures Z.ai chat and advances to optional voice", async () => {
    setupFetch({
      provider: {
        ...defaultProviderSettings,
        openrouter: { configured: false, chat_model: null, tts_model: null, tts_voice: null },
        zai: { configured: false, endpoint: "coding-global", chat_model: null },
        codex: { configured: false, chat_model: null },
      },
    });

    render(<ProviderSetupStepper />);

    await userEvent.click(await screen.findByRole("button", { name: /z\.ai api key/i }));
    expect((screen.getByLabelText(/chat model/i) as HTMLInputElement).value).toBe("glm-5.1");
    await userEvent.type(screen.getByLabelText(/api key/i), "zai-test");
    await userEvent.click(screen.getByRole("button", { name: /use z\.ai/i }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            url === "/api/settings/providers/zai" &&
            (init as FetchInit | undefined)?.method === "PUT" &&
            JSON.parse((init as FetchInit).body as string).chat_model === "glm-5.1",
        ),
      ).toBe(true);
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            url === "/api/settings/providers/preferred-chat" &&
            (init as FetchInit | undefined)?.method === "PUT" &&
            JSON.parse((init as FetchInit).body as string).preferred_chat_provider ===
              "zai",
        ),
      ).toBe(true);
    });
    expect(await screen.findByRole("heading", { name: /voice is optional/i })).toBeInTheDocument();
  });

  it("saves optional voice without changing the preferred chat provider", async () => {
    setupFetch({
      provider: {
        ...defaultProviderSettings,
        openrouter: { configured: false, chat_model: null, tts_model: null, tts_voice: null },
        codex: { configured: true, chat_model: "gpt-5.5" },
      },
    });

    render(<ProviderSetupStepper />);

    expect(await screen.findByRole("heading", { name: /voice is optional/i })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/openrouter api key/i), "sk-or-voice");
    await userEvent.click(screen.getByRole("button", { name: /set up voice/i }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            url === "/api/settings/providers/openrouter" &&
            (init as FetchInit | undefined)?.method === "PUT" &&
            JSON.parse((init as FetchInit).body as string).tts_model ===
              "canopylabs/orpheus-3b-0.1-ft",
        ),
      ).toBe(true);
      expect(refetchMock).toHaveBeenCalled();
    });
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) =>
          url === "/api/settings/providers/preferred-chat" &&
          (init as FetchInit | undefined)?.method === "PUT",
      ),
    ).toBe(false);
  });

  it("lets users skip optional voice before continuing to chat onboarding", async () => {
    setupFetch({
      provider: {
        ...defaultProviderSettings,
        codex: { configured: true, chat_model: "gpt-5.5" },
      },
    });

    render(<ProviderSetupStepper />);

    expect(await screen.findByRole("heading", { name: /voice is optional/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /skip voice/i }));
    expect(refetchMock).toHaveBeenCalled();
  });
});


describe("SettingsPanel — OpenRouter TTS voice", () => {
  function openRouterForm() {
    const voiceSelect = screen.getByRole("combobox", { name: /tts voice/i });
    const form = voiceSelect.closest("form");
    if (!form) throw new Error("OpenRouter voice select is not inside a form");
    return form;
  }

  function openRouterProviderSettings(
    openrouter: OpenRouterBlock,
  ) {
    return {
      ...defaultProviderSettings,
      openrouter,
    };
  }

  it("loads and saves a common OpenRouter TTS voice", async () => {
    setupFetch({
      provider: openRouterProviderSettings({
        configured: true,
        chat_model: "openrouter/auto",
        tts_model: "canopylabs/orpheus-3b-0.1-ft",
        tts_voice: "tara",
      }),
    });
    render(<SettingsPanel />);

    const voiceSelect = await screen.findByRole("combobox", { name: /tts voice/i });
    await waitFor(() => expect(voiceSelect).toHaveTextContent("tara"));

    await userEvent.click(voiceSelect);
    await userEvent.click(await screen.findByRole("option", { name: "leah" }));

    await userEvent.click(within(openRouterForm()).getByRole("button", { name: /save/i }));

    await waitFor(() => {
      const putCalls = fetchMock.mock.calls.filter(
        ([url, init]) =>
          url === "/api/settings/providers/openrouter" &&
          (init as FetchInit | undefined)?.method === "PUT",
      );
      expect(putCalls).toHaveLength(1);
      expect(JSON.parse(putCalls[0][1].body as string)).toMatchObject({
        tts_model: "canopylabs/orpheus-3b-0.1-ft",
        tts_voice: "leah",
      });
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            url === "/api/settings/providers/preferred-chat" &&
            (init as FetchInit | undefined)?.method === "PUT",
        ),
      ).toBe(false);
    });
  });

  it("updates TTS voice choices when selecting a different common TTS model", async () => {
    setupFetch({
      provider: openRouterProviderSettings({
        configured: true,
        chat_model: "openrouter/auto",
        tts_model: "canopylabs/orpheus-3b-0.1-ft",
        tts_voice: "tara",
      }),
    });
    render(<SettingsPanel />);

    const modelSelect = await screen.findByRole("combobox", { name: /tts model/i });
    await userEvent.click(modelSelect);
    await userEvent.click(
      await screen.findByRole("option", { name: /OpenAI GPT-4o mini TTS/i }),
    );

    const voiceSelect = screen.getByRole("combobox", { name: /tts voice/i });
    await waitFor(() => expect(voiceSelect).toHaveTextContent("alloy"));
    await userEvent.click(voiceSelect);
    await userEvent.click(await screen.findByRole("option", { name: "nova" }));

    await userEvent.click(within(openRouterForm()).getByRole("button", { name: /save/i }));

    await waitFor(() => {
      const putCalls = fetchMock.mock.calls.filter(
        ([url, init]) =>
          url === "/api/settings/providers/openrouter" &&
          (init as FetchInit | undefined)?.method === "PUT",
      );
      expect(putCalls).toHaveLength(1);
      expect(JSON.parse(putCalls[0][1].body as string)).toMatchObject({
        tts_model: "openai/gpt-4o-mini-tts-2025-12-15",
        tts_voice: "nova",
      });
    });
  });

  it("preserves arbitrary custom TTS model and voice strings", async () => {
    setupFetch({
      provider: openRouterProviderSettings({
        configured: true,
        chat_model: "openrouter/auto",
        tts_model: "custom/provider-tts",
        tts_voice: "custom_voice",
      }),
    });
    render(<SettingsPanel />);

    const customModel = (await screen.findByLabelText(/custom tts model/i)) as HTMLInputElement;
    await waitFor(() => expect(customModel.value).toBe("custom/provider-tts"));
    const customVoice = screen.getByLabelText(/custom tts voice/i) as HTMLInputElement;
    expect(customVoice.value).toBe("custom_voice");

    await userEvent.clear(customModel);
    await userEvent.type(customModel, "other/provider-tts");
    await userEvent.clear(customVoice);
    await userEvent.type(customVoice, "bespoke_voice");
    await userEvent.click(within(openRouterForm()).getByRole("button", { name: /save/i }));

    await waitFor(() => {
      const putCalls = fetchMock.mock.calls.filter(
        ([url, init]) =>
          url === "/api/settings/providers/openrouter" &&
          (init as FetchInit | undefined)?.method === "PUT",
      );
      expect(putCalls).toHaveLength(1);
      expect(JSON.parse(putCalls[0][1].body as string)).toMatchObject({
        tts_model: "other/provider-tts",
        tts_voice: "bespoke_voice",
      });
    });
  });
});
