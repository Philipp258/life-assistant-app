import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  getPermissionState,
  isIos,
  isPushSupported,
  isStandalone,
  isSubscribed,
  subscribePush,
  unsubscribePush,
  type PushPermission,
  type SubscribeResult,
} from "@/lib/push";
import { useIdentity } from "@/shell/identity";

type Status =
  | { kind: "idle" }
  | { kind: "working" }
  | { kind: "ok"; message: string }
  | { kind: "error"; message: string };

export function NotificationsPanel() {
  const { assistantName } = useIdentity();
  const [permission, setPermission] = useState<PushPermission>("default");
  const [subscribed, setSubscribed] = useState(false);
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  const refresh = async () => {
    setPermission(getPermissionState());
    setSubscribed(await isSubscribed());
  };

  useEffect(() => {
    refresh();
  }, []);

  const onEnable = async () => {
    setStatus({ kind: "working" });
    const result: SubscribeResult = await subscribePush();
    if (result.status === "subscribed") {
      setStatus({ kind: "ok", message: "Notifications enabled." });
    } else if (result.status === "denied") {
      setStatus({
        kind: "error",
        message: "Permission denied. Allow notifications in your browser settings.",
      });
    } else if (result.status === "needs-standalone") {
      setStatus({
        kind: "error",
        message:
          "On iOS, tap Share -> Add to Home Screen, then open Life Assistant from your home screen and try again.",
      });
    } else if (result.status === "unsupported") {
      setStatus({
        kind: "error",
        message: "This browser doesn't support Web Push.",
      });
    } else {
      setStatus({ kind: "error", message: result.message });
    }
    await refresh();
  };

  const onDisable = async () => {
    setStatus({ kind: "working" });
    try {
      await unsubscribePush();
      setStatus({ kind: "ok", message: "Notifications disabled." });
    } catch (e) {
      setStatus({
        kind: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    }
    await refresh();
  };

  const supported = isPushSupported();
  const iosNeedsInstall = isIos() && !isStandalone();

  return (
    <div className="flex h-full flex-col overflow-y-auto p-4 gap-4">
      <div className="flex flex-col gap-1">
        <h2 className="text-sm font-semibold">Notifications</h2>
        <p className="text-xs text-life-ink-3">
          Get a push when {assistantName} writes you, when a task is handed back, when
          a task is due, or when a run keeps erroring.
        </p>
      </div>

      <div className="flex flex-col gap-3 text-sm">
        {!supported && (
          <p className="text-life-ink-3">
            This browser doesn't support Web Push. Try a recent Chrome,
            Firefox, or Safari (iOS 16.4+).
          </p>
        )}

        {supported && iosNeedsInstall && (
          <p className="text-life-ink-3">
            On iOS, push only works after you install Life Assistant: tap the share
            icon in Safari, choose <em>Add to Home Screen</em>, then open
            Life Assistant from your home screen and come back here.
          </p>
        )}

        {supported && !iosNeedsInstall && (
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span>Permission</span>
              <span className="font-mono text-xs">{permission}</span>
            </div>
            <div className="flex items-center justify-between">
              <span>Subscribed on this device</span>
              <span className="font-mono text-xs">
                {subscribed ? "yes" : "no"}
              </span>
            </div>
          </div>
        )}

        {status.kind === "ok" && (
          <p className="text-green-600">{status.message}</p>
        )}
        {status.kind === "error" && (
          <p className="text-red-500">{status.message}</p>
        )}
      </div>

      {supported && !iosNeedsInstall && !subscribed && (
        <Button onClick={onEnable} disabled={status.kind === "working"} className="self-start">
          {status.kind === "working" ? "Working…" : "Enable"}
        </Button>
      )}
      {supported && !iosNeedsInstall && subscribed && (
        <Button
          variant="outline"
          onClick={onDisable}
          disabled={status.kind === "working"}
          className="self-start"
        >
          {status.kind === "working" ? "Working…" : "Disable"}
        </Button>
      )}
    </div>
  );
}
