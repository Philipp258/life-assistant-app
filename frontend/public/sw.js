// Life Assistant service worker. Owns Web Push delivery and click-to-focus.
//
// Backend payload shape (see app/notifications/service.py):
//   { title, body, url, event_type, tag }
//
// We don't precache or do offline; browsers register us solely for the
// Push API. `notificationclick` focuses an existing tab on the deep
// link if one is open, else opens a new window.

self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (_e) {
    data = { title: "Life Assistant", body: event.data ? event.data.text() : "" };
  }

  const title = data.title || "Life Assistant";
  const options = {
    body: data.body || "",
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    tag: data.tag || data.event_type || "life-assistant",
    renotify: true,
    data: { url: data.url || "/" },
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";

  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((clientsList) => {
        for (const client of clientsList) {
          const url = new URL(client.url);
          if (url.pathname === target && "focus" in client) {
            return client.focus();
          }
        }
        for (const client of clientsList) {
          if ("navigate" in client && "focus" in client) {
            return client.navigate(target).then(() => client.focus());
          }
        }
        return self.clients.openWindow(target);
      }),
  );
});
