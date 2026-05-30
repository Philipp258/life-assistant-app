import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mountEvents: string[] = [];

vi.mock("@/screens/Chat/ChatScreen", () => ({
  ChatScreen: () => {
    useEffect(() => {
      mountEvents.push("chat:mount");
      return () => {
        mountEvents.push("chat:unmount");
      };
    }, []);
    return <div data-testid="chat-screen">chat</div>;
  },
}));

vi.mock("@/screens/Tasks/TasksScreen", () => ({
  TasksScreen: () => <div data-testid="tasks-screen">tasks</div>,
}));

vi.mock("@/screens/Tasks/TaskDetailPage", () => ({
  TaskDetailPage: () => <div>task detail</div>,
}));

vi.mock("@/screens/Goals/GoalsScreen", () => ({
  GoalsScreen: () => <div>goals</div>,
}));

vi.mock("@/screens/Goals/GoalDetailPage", () => ({
  GoalDetailPage: () => <div>goal detail</div>,
}));

vi.mock("@/screens/Knowledge/KnowledgeScreen", () => ({
  KnowledgeScreen: () => <div>know</div>,
}));

vi.mock("@/screens/Knowledge/KnowledgeDetailRoute", () => ({
  KnowledgeDetailRoute: () => <div>know detail</div>,
  CoreMemoryRoute: () => <div>core memory</div>,
  SkillRoute: () => <div>skill</div>,
}));

vi.mock("@/screens/Agent/AgentScreen", () => ({
  AgentScreen: () => <div>agent</div>,
}));

vi.mock("@/screens/Auth/LoginScreen", () => ({
  LoginScreen: () => <div>login</div>,
}));

vi.mock("@/screens/Onboarding/ProviderSetupScreen", () => ({
  ProviderSetupScreen: () => <div>provider setup</div>,
}));

const identityValue = {
  assistantName: "Nix",
  isOnboarding: false,
  onboardingState: "done" as const,
  refetch: () => {},
};
vi.mock("@/shell/identity", () => ({
  IdentityProvider: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
  useIdentity: () => identityValue,
}));

vi.mock("@/shell/AppShell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));

import { AppRoutes } from "./App";

function NavButtons() {
  const navigate = useNavigate();
  return (
    <>
      <button onClick={() => navigate("/chat")}>go-chat</button>
      <button onClick={() => navigate("/tasks")}>go-tasks</button>
    </>
  );
}

beforeEach(() => {
  mountEvents.length = 0;
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("AppRoutes — chat persistence across navigation", () => {
  it("renders ChatScreen visibly when on /chat", () => {
    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <AppRoutes />
        <NavButtons />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("chat-screen")).toBeInTheDocument();
    const overlay = screen.getByTestId("chat-overlay");
    expect(overlay).not.toHaveClass("hidden");
    expect(overlay).toHaveAttribute("aria-hidden", "false");
  });

  it("keeps ChatScreen mounted (hidden) when navigating away mid-stream", async () => {
    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <AppRoutes />
        <NavButtons />
      </MemoryRouter>,
    );

    expect(mountEvents).toEqual(["chat:mount"]);

    await userEvent.click(screen.getByText("go-tasks"));

    // Tasks is now the active route...
    expect(screen.getByTestId("tasks-screen")).toBeInTheDocument();
    // ...but ChatScreen is still mounted in the DOM, just hidden. This is
    // what makes navigating away during a streaming answer non-destructive.
    expect(screen.getByTestId("chat-screen")).toBeInTheDocument();
    const overlay = screen.getByTestId("chat-overlay");
    expect(overlay).toHaveClass("hidden");
    expect(overlay).toHaveAttribute("aria-hidden", "true");
    // No unmount happened — same instance.
    expect(mountEvents).toEqual(["chat:mount"]);
  });

  it("returns to the same ChatScreen instance when navigating back to /chat", async () => {
    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <AppRoutes />
        <NavButtons />
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByText("go-tasks"));
    await userEvent.click(screen.getByText("go-chat"));

    expect(screen.getByTestId("chat-screen")).toBeInTheDocument();
    expect(screen.getByTestId("chat-overlay")).not.toHaveClass("hidden");
    // ChatScreen mounted exactly once across both navigations.
    expect(mountEvents).toEqual(["chat:mount"]);
  });

  it("mounts ChatScreen even when initial route is not /chat", () => {
    render(
      <MemoryRouter initialEntries={["/tasks"]}>
        <AppRoutes />
        <NavButtons />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("tasks-screen")).toBeInTheDocument();
    // ChatScreen is mounted (so a future visit picks up its state) but
    // hidden because we're on a different tab.
    expect(screen.getByTestId("chat-screen")).toBeInTheDocument();
    expect(screen.getByTestId("chat-overlay")).toHaveClass("hidden");
    expect(mountEvents).toEqual(["chat:mount"]);
  });
});
