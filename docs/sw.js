/**
 * 開示レーダー — Service Worker (sw.js)
 * App shell: cache-first
 * ./data/*:  network-first, fallback to cache
 */

'use strict';

const CACHE_VERSION = 'kaiji-v1';
const SHELL_CACHE   = `${CACHE_VERSION}-shell`;
const DATA_CACHE    = `${CACHE_VERSION}-data`;

const SHELL_ASSETS = [
  './',
  './index.html',
  './app.js',
  './style.css',
  './icon.svg',
  './manifest.webmanifest',
];

/* ===== Install ===== */
self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
  );
});

/* ===== Activate: purge old caches ===== */
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== SHELL_CACHE && k !== DATA_CACHE)
          .map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

/* ===== Fetch ===== */
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  // data/* → network-first, fallback to cache
  if (url.pathname.includes('/data/')) {
    e.respondWith(networkFirstData(e.request));
    return;
  }

  // shell assets → cache-first
  if (e.request.method === 'GET') {
    e.respondWith(cacheFirstShell(e.request));
  }
});

async function networkFirstData(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(DATA_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    return cached || new Response('{"error":"offline"}', {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}

async function cacheFirstShell(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(SHELL_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    // If it's a navigation request, return the cached index
    if (request.mode === 'navigate') {
      return caches.match('./index.html');
    }
    throw new Error('offline');
  }
}
