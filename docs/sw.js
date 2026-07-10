/**
 * 開示レーダー — Service Worker (sw.js)
 * App shell: network-first (fetch success → update cache; fetch fail → cache fallback)
 * ./data/*:  network-first, fallback to cache
 */

'use strict';

const CACHE_VERSION = 'kaiji-v2';
const SHELL_CACHE   = `${CACHE_VERSION}-shell`;
const DATA_CACHE    = `${CACHE_VERSION}-data`;

// index.html が読み込む app.js/style.css の実URL(?v=2 付き)と一致させること。
// ずれると同一リソースに対して versioned/unversioned の2つのキャッシュエントリが
// 併存し、ignoreSearch でのフォールバック参照時にどちらが返るか不定になり、
// 古い方が返って更新が反映されない不具合の原因になる。
const ASSET_VERSION = '2'; // index.html の ?v=2 と必ず一致させる

const SHELL_ASSETS = [
  './',
  './index.html',
  `./app.js?v=${ASSET_VERSION}`,
  `./style.css?v=${ASSET_VERSION}`,
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

/* ===== Message: allow page to force-activate a waiting SW ===== */
self.addEventListener('message', (e) => {
  if (e.data && e.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

/* ===== Fetch ===== */
self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET') return;

  const url = new URL(e.request.url);

  // data/* → network-first, fallback to cache
  if (url.pathname.includes('/data/')) {
    e.respondWith(networkFirstData(e.request));
    return;
  }

  // app shell (HTML/JS/CSS/SVG/manifest) → network-first, fallback to cache
  e.respondWith(networkFirstShell(e.request));
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
    const cached = await caches.match(request, { ignoreSearch: true });
    return cached || new Response('{"error":"offline"}', {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}

async function networkFirstShell(request) {
  try {
    // ブラウザのHTTPディスクキャッシュ(ヒューリスティック鮮度判定)を迂回し、
    // 常に実ネットワークへ問い合わせる。Safari含む各ブラウザでの
    // 「SWはnetwork-firstのつもりが実はHTTPキャッシュから古いレスポンスを
    // 受け取ってしまう」事象を防ぐため。
    const response = await fetch(request, { cache: 'no-store' });
    if (response.ok) {
      const cache = await caches.open(SHELL_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request, { ignoreSearch: true });
    if (cached) return cached;
    // If it's a navigation request, return the cached index as last resort
    if (request.mode === 'navigate') {
      const cachedIndex = await caches.match('./index.html', { ignoreSearch: true });
      if (cachedIndex) return cachedIndex;
    }
    throw new Error('offline');
  }
}
