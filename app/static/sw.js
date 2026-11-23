// Service worker das Âncoras: abre offline com a última versão da tela e dos dados.
// HTML e API: rede primeiro (dados sempre frescos), cache só como reserva.
const CACHE = "kaizen-v1";
const SHELL = ["/", "/jogo.js", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL).catch(() => {})).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin) return;
  if (u.searchParams.has("k")) return;            // link de login: nunca cachear
  if (u.pathname === "/api/webhook") return;      // contém token
  e.respondWith(
    fetch(e.request).then(r => {
      if (r.ok && (u.pathname === "/" || u.pathname.startsWith("/api/checkins") || u.pathname.startsWith("/api/saude") || SHELL.includes(u.pathname))) {
        const copia = r.clone();
        const chave = u.pathname === "/" ? "/" : e.request;
        caches.open(CACHE).then(c => c.put(chave, copia));
      }
      return r;
    }).catch(() => caches.match(u.pathname === "/" ? "/" : e.request))
  );
});
