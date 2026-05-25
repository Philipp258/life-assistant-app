import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { apiFetch } from "@/lib/api";

export type OnboardingState = "needs_provider" | "needs_chat" | "done";

export type Identity = {
  assistantName: string;
  isOnboarding: boolean;
  onboardingState: OnboardingState;
};

type IdentityState =
  | { kind: "loading" }
  | { kind: "ready"; identity: Identity; refetch: () => void }
  | { kind: "error"; message: string; refetch: () => void };

const FALLBACK: Identity = {
  assistantName: "Assistant",
  isOnboarding: false,
  onboardingState: "done",
};

const IdentityContext = createContext<IdentityState>({ kind: "loading" });

async function fetchIdentity(): Promise<Identity> {
  const r = await apiFetch("/api/identity");
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  const body = (await r.json()) as {
    assistant_name: string;
    is_onboarding: boolean;
    onboarding_state?: OnboardingState;
  };
  return {
    assistantName: body.assistant_name,
    isOnboarding: body.is_onboarding,
    onboardingState: body.onboarding_state ?? (body.is_onboarding ? "needs_chat" : "done"),
  };
}

export function IdentityProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<IdentityState>({ kind: "loading" });

  const load = useMemo(
    () => () => {
      setState((prev) => (prev.kind === "ready" ? prev : { kind: "loading" }));
      fetchIdentity()
        .then((identity) =>
          setState({ kind: "ready", identity, refetch: load }),
        )
        .catch((e) =>
          setState({
            kind: "error",
            message: e instanceof Error ? e.message : String(e),
            refetch: load,
          }),
        );
    },
    [],
  );

  useEffect(() => {
    load();
  }, [load]);

  // While chat-onboarding, poll so the UI flips back to normal (TabBar shown,
  // routes restored) the moment the agent calls `mark_onboarded`. Provider
  // setup is an explicit stepper; it calls refetch when the user finishes so
  // the optional voice step does not get skipped by a background poll.
  useEffect(() => {
    if (
      state.kind !== "ready" ||
      !state.identity.isOnboarding ||
      state.identity.onboardingState !== "needs_chat"
    ) {
      return;
    }
    const id = window.setInterval(load, 4000);
    return () => window.clearInterval(id);
  }, [state, load]);

  return (
    <IdentityContext.Provider value={state}>
      {children}
    </IdentityContext.Provider>
  );
}

export function useIdentity(): Identity & { refetch: () => void } {
  const state = useContext(IdentityContext);
  if (state.kind === "ready") {
    return { ...state.identity, refetch: state.refetch };
  }
  return { ...FALLBACK, refetch: () => {} };
}

export function useIdentityState(): IdentityState {
  return useContext(IdentityContext);
}
