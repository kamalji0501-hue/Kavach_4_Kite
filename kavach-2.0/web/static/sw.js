/* Kavach desk service worker — installability only. Live data always from network. */
const CACHE = "kavach-shell-v1";
const SHELL = [
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/logo.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(SHELL)).catch(() => undefined)
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/ws/")) return;
  if (req.headers.get("upgrade") === "websocket") return;

  event.respondWith(
    fetch(req)
      .then((resp) => resp)
      .catch(() => caches.match(req).then((hit) => hit || caches.match("/")))
  );
});
