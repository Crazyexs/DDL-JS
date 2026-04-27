/* Map tile cache service worker — caches tiles on first fetch, serves from cache offline */

const CACHE = 'map-tiles-v1';

// Hostnames whose responses should be cached (map tile providers only)
const TILE_HOSTS = new Set([
  'tile.openstreetmap.org',
  'a.tile.openstreetmap.org',
  'b.tile.openstreetmap.org',
  'c.tile.openstreetmap.org',
  'services.arcgisonline.com',
]);

function isTileRequest(url) {
  return TILE_HOSTS.has(url.hostname);
}

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;

  const url = new URL(event.request.url);
  if (!isTileRequest(url)) return;

  event.respondWith(
    caches.open(CACHE).then(cache =>
      cache.match(event.request).then(cached => {
        if (cached) return cached;
        return fetch(event.request).then(response => {
          if (response.ok) cache.put(event.request, response.clone());
          return response;
        }).catch(() => {
          // No network, no cache — return 204 so Cesium/Leaflet skips gracefully
          return new Response('', { status: 204 });
        });
      })
    )
  );
});
