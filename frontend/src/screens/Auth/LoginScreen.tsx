import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiFetch } from "@/lib/api";

export function LoginScreen() {
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      const r = await apiFetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (r.ok) {
        navigate("/", { replace: true });
        return;
      }
      if (r.status === 401) {
        setError("Wrong password");
      } else {
        setError(`${r.status} ${r.statusText}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex h-full w-full justify-center bg-[#E8E3D8]">
      <div className="flex h-full w-full max-w-[480px] flex-col items-center justify-center gap-8 bg-life-bg px-6 text-life-ink">
        <div className="text-3xl font-semibold tracking-tight">
          Life Assistant
        </div>
        <form
          onSubmit={onSubmit}
          className="flex w-full flex-col gap-3"
          aria-label="Sign in"
        >
          <Label htmlFor="login-password">Password</Label>
          <Input
            id="login-password"
            type="password"
            autoFocus
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={pending}
          />
          {error && (
            <div role="alert" className="text-sm text-destructive">
              {error}
            </div>
          )}
          <Button type="submit" disabled={pending || password.length === 0}>
            {pending ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </div>
    </div>
  );
}
