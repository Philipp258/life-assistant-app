import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/screens/Chat/ChatScreen", () => ({
  ChatScreen: () => <div data-testid="chat-screen">chat</div>,
}));

vi.mock("@/screens/Agent/SettingsPanel", () => ({
  SettingsPanel: () => <div data-testid="settings-panel">settings</div>,
}));

import { OnboardingChatScreen } from "./OnboardingChatScreen";

afterEach(() => {
  vi.clearAllMocks();
});

describe("OnboardingChatScreen — escape hatch", () => {
  it("shows the chat with a provider-settings escape, hidden by default", () => {
    render(<OnboardingChatScreen />);

    expect(screen.getByTestId("chat-screen")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /provider settings/i }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("settings-panel")).not.toBeInTheDocument();
  });

  it("opens provider settings and closes back to the chat", async () => {
    render(<OnboardingChatScreen />);

    await userEvent.click(
      screen.getByRole("button", { name: /provider settings/i }),
    );
    expect(screen.getByTestId("settings-panel")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: /close provider settings/i }),
    );
    expect(screen.queryByTestId("settings-panel")).not.toBeInTheDocument();
    expect(screen.getByTestId("chat-screen")).toBeInTheDocument();
  });
});
