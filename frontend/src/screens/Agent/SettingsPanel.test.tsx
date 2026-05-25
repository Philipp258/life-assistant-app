import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsPanel } from "./SettingsPanel";
import type { OpenRouterBlock } from "./providerApi";
import type { RuntimeSettings } from "./runtimeSettingsApi";

const fetchMock = vi.fn();

vi.mock("@/shell/identity", () => ({
  useIdentity: () => ({ refetch: vi.fn() }),
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

function setupFetch(
  options: {
    runtime?: Partial<RuntimeSettings>;
    provider?: Record<string, unknown>;
  } = {},
) {
  const provider = options.provider ?? defaultProviderSettings;
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
  function providerForm(label: RegExp) {
    const input = screen.getByLabelText(label);
    const form = input.closest("form");
    if (!form) throw new Error("Provider input is not inside a form");
    return form;
  }

  it("PUTs Codex auth and model when the Codex Save button is clicked", async () => {
    setupFetch({
      provider: {
        ...defaultProviderSettings,
        codex: { configured: false, chat_model: null },
      },
    });
    render(<SettingsPanel />);

    const auth = await screen.findByLabelText(/auth\.json contents/i);
    await userEvent.type(auth, "codex-auth-json");
    await userEvent.type(
      screen.getByLabelText(/chat model/i, { selector: "#codex-model" }),
      "gpt-5.5",
    );
    await userEvent.click(
      within(providerForm(/auth\.json contents/i)).getByRole("button", {
        name: /save chatgpt subscription/i,
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
        auth_json: "codex-auth-json",
        chat_model: "gpt-5.5",
      });
    });
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
