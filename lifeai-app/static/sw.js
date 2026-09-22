// Service Worker: App offline verfügbar machen + Push-Benachrichtigungen anzeigen
const VERSION = 'lifeai-v1';
const SHELL = ['/', '/index.html', '/style.css', '/app.js', '/manifest.webmanifest', '/icons/icon-192.png', '/icons/icon-512.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/')) {
    // Daten: erst Netz, bei Offline den letzten Stand aus dem Cache
    e.respondWith(fetch(e.request).then((r) => {
      if (r.ok) { const kopie = r.clone(); caches.open(VERSION).then((c) => c.put(e.request, kopie)); }
      return r;
    }).catch(() => caches.match(e.request)));
    return;
  }
  // App-Dateien: sofort aus dem Cache, im Hintergrund aktualisieren
  e.respondWith(caches.match(e.request).then((alt) => {
    const neu = fetch(e.request).then((r) => {
      if (r.ok && r.type === 'basic') { const kopie = r.clone(); caches.open(VERSION).then((c) => c.put(e.request, kopie)); }
      return r;
    }).catch(() => alt);
    return alt || neu;
  }));
});

self.addEventListener('push', (e) => {
  let d = {};
  try { d = e.data.json(); } catch (_) { d = { title: 'LifeAI', body: e.data ? e.data.text() : '' }; }
  e.waitUntil(self.registration.showNotification(d.title || 'LifeAI', {
    body: d.body || '',
    icon: '/icons/icon-192.png',
    badge: '/icons/badge-96.png',
    tag: d.tag || undefined,
    renotify: !!d.tag,
    data: { url: d.url || '/' },
  }));
});

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const ziel = e.notification.data?.url || '/';
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((fenster) => {
    for (const f of fenster) { if ('focus' in f) { f.navigate(ziel); return f.focus(); } }
    return self.clients.openWindow(ziel);
  }));
});
