import { useCallback } from "react";
import { useNavigate } from "react-router-dom";

/**
 * Browser-like back: pop the previous in-app entry, or navigate to
 * `fallback` if this is the first entry of the session (deep link,
 * page refresh, etc.) so the user does not get bounced out of the SPA.
 *
 * React Router v6 stores an `idx` on history state; `idx === 0` means
 * we are at the entry the tab was opened on.
 */
export function useGoBack(fallback: string) {
  const navigate = useNavigate();
  return useCallback(() => {
    const idx = (window.history.state as { idx?: number } | null)?.idx;
    if (typeof idx === "number" && idx > 0) {
      navigate(-1);
    } else {
      navigate(fallback);
    }
  }, [navigate, fallback]);
}
