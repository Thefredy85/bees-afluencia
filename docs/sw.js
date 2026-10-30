// Service worker: recibe los avisos del monitor y los muestra aunque la app esté cerrada.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

self.addEventListener('push', e => {
  let d = {};
  try { d = e.data.json(); } catch (x) { d = { titulo: "Bee's Pizza's", cuerpo: e.data ? e.data.text() : '' }; }
  e.waitUntil(self.registration.showNotification(d.titulo || "Bee's Pizza's", {
    body: d.cuerpo || '',
    tag: d.etiqueta || 'afluencia',   // un aviso nuevo del mismo tipo reemplaza al anterior
    renotify: true,
    icon: 'icon-192.png',
    badge: 'icon-192.png',
    vibrate: [200, 100, 200],
  }));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(ventanas => {
    for (const v of ventanas) if ('focus' in v) return v.focus();
    return clients.openWindow('./');
  }));
});
