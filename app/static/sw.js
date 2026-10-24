// __APP_VERSION__ ersetzt main.py beim Ausliefern durch die App-Version: jede
// neue Version ergibt einen neuen Cache, alte Stände (z.B. style.css) fliegen raus.
const CACHE_NAME = "agent-static-__APP_VERSION__";
const STATIC_ASSETS = [
  "/static/style.css",
  "/static/agent.png",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      // cache: "reload" umgeht den HTTP-Cache, sonst landet evtl. die alte Datei im neuen Cache
      .then((cache) => cache.addAll(STATIC_ASSETS.map((url) => new Request(url, { cache: "reload" }))))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
      )
  );
  self.clients.claim();
});

// Nur die statischen App-Shell-Assets cachen - alle dynamischen Seiten
// (Geräteträger-Daten etc.) laufen immer über das Netzwerk, damit nie
// veraltete Tauglichkeits-/Termindaten angezeigt werden.
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (!STATIC_ASSETS.includes(url.pathname)) return;

  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
