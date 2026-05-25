import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getPermissionState,
  isIos,
  isStandalone,
  subscribePush,
  unsubscribePush,
} from "./push";

const VAPID_KEY_B64 =
  "BNNL5ZWVdcA-eAhVN5b8e7L1G6dNlOcGqU6IqQwDz6gM4hkV3vQ_vUf6vU4-N5Q7gO5DgL2g4mE5p1JvL5J2K6E";

type SubMock = {
  endpoint: string;
  toJSON: () => unknown;
  unsubscribe: ReturnType<typeof vi.fn>;
};

let fakeSubscription: SubMock;

const pushManagerMock = {
  getSubscription: vi.fn(),
  subscribe: vi.fn(),
};

const registrationMock = {
  pushManager: pushManagerMock,
};

const swMock = {
  register: vi.fn(),
  ready: Promise.resolve(registrationMock),
  getRegistration: vi.fn(),
};

beforeEach(() => {
  fakeSubscription = {
    endpoint: "https://push.example.com/abc",
    toJSON() {
      return {
        endpoint: this.endpoint,
        keys: { p256dh: "P256DH", auth: "AUTH" },
      };
    },
    unsubscribe: vi.fn().mockResolvedValue(true),
  };

  pushManagerMock.getSubscription.mockReset().mockResolvedValue(null);
  pushManagerMock.subscribe.mockReset().mockResolvedValue(fakeSubscription);
  swMock.register.mockReset().mockResolvedValue(registrationMock);
  swMock.getRegistration.mockReset().mockResolvedValue(registrationMock);

  // Augment jsdom's existing globals — don't replace them, just stamp on
  // what `push.ts` checks for.
  (navigator as unknown as { serviceWorker: typeof swMock }).serviceWorker =
    swMock;
  Object.defineProperty(navigator, "userAgent", {
    configurable: true,
    value: "Mozilla/5.0 (X11; Linux x86_64) Chrome/120",
  });

  (window as unknown as { PushManager: unknown }).PushManager = function () {};
  (window as unknown as { Notification: unknown }).Notification = {
    permission: "default",
    requestPermission: vi.fn().mockResolvedValue("granted"),
  };
  // The push module reads the bare global `Notification` identifier too.
  (globalThis as unknown as { Notification: unknown }).Notification = (
    window as unknown as { Notification: unknown }
  ).Notification;

  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : (input as Request).url ?? input.toString();
    if (url.endsWith("/api/push/vapid-public-key")) {
      return new Response(JSON.stringify({ key: VAPID_KEY_B64 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.endsWith("/api/push/subscribe")) {
      return new Response(JSON.stringify({ id: 1 }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response("not mocked: " + url, { status: 500 });
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("push.subscribePush", () => {
  it("registers SW, fetches VAPID key, subscribes, posts to backend", async () => {
    const result = await subscribePush();
    expect(result).toEqual({ status: "subscribed" });
    expect(swMock.register).toHaveBeenCalledWith("/sw.js");
    expect(pushManagerMock.subscribe).toHaveBeenCalledWith(
      expect.objectContaining({ userVisibleOnly: true }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/push/vapid-public-key",
      expect.any(Object),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/push/subscribe",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining(fakeSubscription.endpoint),
      }),
    );
  });

  it("returns denied when the user blocks the permission prompt", async () => {
    (window as unknown as { Notification: { requestPermission: () => Promise<string> } })
      .Notification.requestPermission = vi.fn().mockResolvedValue("denied");
    const result = await subscribePush();
    expect(result).toEqual({ status: "denied" });
    expect(swMock.register).not.toHaveBeenCalled();
  });

  it("returns needs-standalone on iOS Safari outside home-screen mode", async () => {
    Object.defineProperty(navigator, "userAgent", {
      configurable: true,
      value:
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari",
    });
    (navigator as unknown as { standalone?: boolean }).standalone = false;
    const result = await subscribePush();
    expect(result).toEqual({ status: "needs-standalone" });
    expect(swMock.register).not.toHaveBeenCalled();
  });

  it("returns unsupported when PushManager is missing", async () => {
    delete (window as unknown as { PushManager?: unknown }).PushManager;
    const result = await subscribePush();
    expect(result).toEqual({ status: "unsupported" });
    expect(swMock.register).not.toHaveBeenCalled();
  });

  it("reuses an existing subscription instead of creating a new one", async () => {
    pushManagerMock.getSubscription.mockResolvedValue(fakeSubscription);
    const result = await subscribePush();
    expect(result).toEqual({ status: "subscribed" });
    expect(pushManagerMock.subscribe).not.toHaveBeenCalled();
  });
});

describe("push.unsubscribePush", () => {
  it("DELETEs the endpoint and calls subscription.unsubscribe", async () => {
    pushManagerMock.getSubscription.mockResolvedValue(fakeSubscription);
    await unsubscribePush();
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/push/subscribe",
      expect.objectContaining({
        method: "DELETE",
        body: expect.stringContaining(fakeSubscription.endpoint),
      }),
    );
    expect(fakeSubscription.unsubscribe).toHaveBeenCalled();
  });
});

describe("push helpers", () => {
  it("getPermissionState reflects Notification.permission", () => {
    (window as unknown as { Notification: { permission: string } })
      .Notification.permission = "granted";
    expect(getPermissionState()).toBe("granted");
  });

  it("isIos detects iPhone UA", () => {
    Object.defineProperty(navigator, "userAgent", {
      configurable: true,
      value: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)",
    });
    expect(isIos()).toBe(true);
  });

  it("isStandalone false when display-mode media query is false", () => {
    expect(isStandalone()).toBe(false);
  });
});
