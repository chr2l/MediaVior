// Rend la page installable (écran d'accueil, menu Partager) et l'affiche même hors connexion.
const CACHE = "mediavior-tel-v1";
const SHELL = ["/", "/tel.css", "/tel.js", "/manifest.webmanifest", "/icons/icon.svg", "/icons/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/ws/")) return;
  // Réseau d'abord (dernière version), cache en secours. « /?url=… » (Partager) = la page « / ».
  const key = event.request.mode === "navigate" ? "/" : url.pathname;
  event.respondWith(
    fetch(event.request)
      .then((res) => {
        if (res.ok && SHELL.includes(key)) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(key, copy));
        }
        return res;
      })
      .catch(() => caches.match(key)),
  );
});
