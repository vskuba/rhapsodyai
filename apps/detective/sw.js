// Service worker заготовка. Кэширование/офлайн/push - добавляется вместе
// с реальным игровым UI, не частью изоляции подпроекта.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
