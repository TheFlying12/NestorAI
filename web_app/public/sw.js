// Minimal service worker — provides offline shell (app shell model).
// Cache the app shell so iOS/Android can install as a PWA.

const CACHE_NAME = "nestor-shell-v2";
const SHELL_URLS = ["/", "/chat", "/settings"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_URLS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Let API, WebSocket, and cross-origin requests go straight to the network.
  const isApiCall =
    url.pathname.startsWith("/api/") ||
    url.protocol === "wss:" ||
    url.hostname !== self.location.hostname;

  if (isApiCall) return;

  // Navigation requests (HTML pages): network-first so deploys are picked up
  // immediately without a hard refresh. Fall back to cache only when offline.
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          return response;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // Static assets (JS, CSS, fonts): cache-first for performance.
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
