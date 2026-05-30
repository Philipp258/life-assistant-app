import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";

import { AgentScreen } from "@/screens/Agent/AgentScreen";
import { LoginScreen } from "@/screens/Auth/LoginScreen";
import { ChatScreen } from "@/screens/Chat/ChatScreen";
import { GoalDetailPage } from "@/screens/Goals/GoalDetailPage";
import { GoalsScreen } from "@/screens/Goals/GoalsScreen";
import { KnowledgeScreen } from "@/screens/Knowledge/KnowledgeScreen";
import {
  CoreMemoryRoute,
  KnowledgeDetailRoute,
  SkillRoute,
} from "@/screens/Knowledge/KnowledgeDetailRoute";
import { OnboardingChatScreen } from "@/screens/Onboarding/OnboardingChatScreen";
import { ProviderSetupScreen } from "@/screens/Onboarding/ProviderSetupScreen";
import { TaskDetailPage } from "@/screens/Tasks/TaskDetailPage";
import { TasksScreen } from "@/screens/Tasks/TasksScreen";
import { AppShell } from "@/shell/AppShell";
import { IdentityProvider, useIdentity } from "@/shell/identity";

export function AppRoutes() {
  const { onboardingState } = useIdentity();
  const location = useLocation();
  if (onboardingState === "needs_provider") {
    // Step 1 of onboarding: provider config. Block every other route
    // until a row exists in `provider_config` — the agent literally
    // can't respond without one.
    return (
      <Routes>
        <Route path="*" element={<ProviderSetupScreen />} />
      </Routes>
    );
  }
  if (onboardingState === "needs_chat") {
    // Step 2: agent walks the user through the chat onboarding ritual
    // that populates about_user.md / behavior.md. Wrapped so a wrong
    // step-1 credential (agent can't start) isn't a dead end — the
    // user can reopen provider settings from here.
    return (
      <Routes>
        <Route path="*" element={<OnboardingChatScreen />} />
      </Routes>
    );
  }
  // Chat is rendered persistently outside <Routes> so navigating to
  // another tab mid-stream does not unmount it. Tearing down the
  // assistant-ui runtime kills the in-flight fetch and discards local
  // message state — coming back would then show an empty chat even
  // though the run is still committing on the server. Keeping it
  // mounted (and toggled via display) preserves both the streaming
  // connection and the partially rendered assistant message. The
  // matching `<Route path="/chat" />` renders nothing so we don't
  // double-mount.
  const isChat = location.pathname === "/chat";
  return (
    <>
      <div
        data-testid="chat-overlay"
        aria-hidden={!isChat}
        className={isChat ? "absolute inset-0 flex flex-col" : "hidden"}
      >
        <ChatScreen isVisible={isChat} />
      </div>
      <Routes>
        <Route path="/" element={<Navigate to="/chat" replace />} />
        <Route path="/chat" element={null} />
        <Route path="/goals" element={<GoalsScreen />} />
        <Route path="/goals/:goalId" element={<GoalDetailPage />} />
        <Route path="/tasks" element={<TasksScreen />} />
        <Route path="/tasks/:taskId" element={<TaskDetailPage />} />
        <Route path="/know" element={<KnowledgeScreen />} />
        <Route path="/know/open/*" element={<KnowledgeDetailRoute />} />
        <Route path="/know/core/:name" element={<CoreMemoryRoute />} />
        <Route path="/know/skill/:name" element={<SkillRoute />} />
        <Route path="/agent" element={<AgentScreen />} />
        <Route path="/agent/:tab" element={<AgentScreen />} />
        <Route path="*" element={<Navigate to="/chat" replace />} />
      </Routes>
    </>
  );
}

function ProtectedShell() {
  return (
    <IdentityProvider>
      <AppShell>
        <AppRoutes />
      </AppShell>
    </IdentityProvider>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginScreen />} />
        <Route path="*" element={<ProtectedShell />} />
      </Routes>
    </BrowserRouter>
  );
}
