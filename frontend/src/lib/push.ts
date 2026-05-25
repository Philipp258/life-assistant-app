// Web Push subscription helpers. Called from the Notifications panel
// in the Agent screen. Backend endpoints live at /api/push/*.
//
// iOS Safari only honours `pushManager.subscribe` from a page running
// in standalone (Add-to-Home-Screen) mode — the panel surfaces an
// install hint when this returns true.

import { apiFetch, jsonOrThrow } from "@/lib/api";

export type PushPermission = "default" | "granted" | "denied" | "unsupported";

export function isIos(): boolean {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || "";
  return /iPhone|iPad|iPod/.test(ua) ||
    (/Macintosh/.test(ua) && "ontouchend" in document);
}

export function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  // iOS uses navigator.standalone; everyone else uses the display-mode media query.
  const navAny = navigator as unknown as { standalone?: boolean };
  if (navAny.standalone === true) return true;
  return window.matchMedia?.("(display-mode: standalone)")?.matches ?? false;
}

export function isPushSupported(): boolean {
  if (typeof window === "undefined") return false;
  return (
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

export function getPermissionState(): PushPermission {
  if (!isPushSupported()) return "unsupported";
  return Notification.permission as PushPermission;
}

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function fetchVapidKey(): Promise<string> {
  const r = await apiFetch("/api/push/vapid-public-key");
  const body = await jsonOrThrow<{ key: string }>(r);
  return body.key;
}

async function postSubscription(sub: PushSubscription): Promise<void> {
  const json = sub.toJSON();
  const keys = (json as { keys?: { p256dh?: string; auth?: string } }).keys;
  if (!sub.endpoint || !keys?.p256dh || !keys?.auth) {
    throw new Error("subscription missing endpoint or keys");
  }
  const r = await apiFetch("/api/push/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      endpoint: sub.endpoint,
      keys: { p256dh: keys.p256dh, auth: keys.auth },
    }),
  });
  await jsonOrThrow<{ id: number }>(r);
}

export type SubscribeResult =
  | { status: "subscribed" }
  | { status: "unsupported" }
  | { status: "denied" }
  | { status: "needs-standalone" }
  | { status: "error"; message: string };

export async function subscribePush(): Promise<SubscribeResult> {
  if (!isPushSupported()) return { status: "unsupported" };
  if (isIos() && !isStandalone()) {
    return { status: "needs-standalone" };
  }

  const permission = await Notification.requestPermission();
  if (permission !== "granted") return { status: "denied" };

  try {
    const reg = await navigator.serviceWorker.register("/sw.js");
    await navigator.serviceWorker.ready;
    const vapidKey = await fetchVapidKey();
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        // Cast: lib.dom typing wants ArrayBuffer-backed buffer; jsdom and
        // Vite both produce a regular Uint8Array, which is fine at runtime.
        applicationServerKey: urlBase64ToUint8Array(
          vapidKey,
        ) as unknown as BufferSource,
      });
    }
    await postSubscription(sub);
    return { status: "subscribed" };
  } catch (e) {
    return {
      status: "error",
      message: e instanceof Error ? e.message : String(e),
    };
  }
}

export async function unsubscribePush(): Promise<void> {
  if (!isPushSupported()) return;
  const reg = await navigator.serviceWorker.getRegistration();
  if (!reg) return;
  const sub = await reg.pushManager.getSubscription();
  if (!sub) return;
  await apiFetch("/api/push/subscribe", {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ endpoint: sub.endpoint }),
  });
  await sub.unsubscribe();
}

export async function isSubscribed(): Promise<boolean> {
  if (!isPushSupported()) return false;
  const reg = await navigator.serviceWorker.getRegistration();
  if (!reg) return false;
  const sub = await reg.pushManager.getSubscription();
  return !!sub;
}
