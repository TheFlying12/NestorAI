// Minimal service worker — provides offline shell (app shell model).
// Cache the app shell so iOS/Android can install as a PWA.

const CACHE_NAME = "nestor-shell-v1";
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
  // Network-first for API/WS calls; cache-first for shell.
  const url = new URL(event.request.url);
  const isApiCall =
    url.pathname.startsWith("/api/") ||
    url.protocol === "wss:" ||
    url.hostname !== self.location.hostname;

  if (isApiCall) {
    // Let API calls pass through to network — do not cache.
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
