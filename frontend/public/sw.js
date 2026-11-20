// Minimal service worker so Snapback is installable as a PWA.
// It deliberately caches nothing (demo data and dev builds never go stale); it only shows
// a friendly offline screen if a page navigation fails.
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))

const OFFLINE = `<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<body style="margin:0;height:100vh;display:grid;place-items:center;background:#F2F2F7;color:#111111;font:17px system-ui;text-align:center">
<div><div style="font-size:44px;font-weight:700;color:#16A34A">Snapback</div><p>You’re offline. Reconnect and try again.</p></div></body>`

self.addEventListener('fetch', (event) => {
  if (event.request.mode !== 'navigate') return
  event.respondWith(fetch(event.request).catch(() => new Response(OFFLINE, { headers: { 'Content-Type': 'text/html; charset=utf-8' } })))
})
