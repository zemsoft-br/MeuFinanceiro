/* global self, caches, URL, fetch, Response */

const CACHE_PREFIX = 'meufinanceiro-flutter-shell-'
const CACHE_NAME = `${CACHE_PREFIX}v1`
const MANAGED_CACHE_PREFIXES = [CACHE_PREFIX, 'meufinanceiro-shell-']
const PRECACHE_ASSETS = [
  '/',
  '/index.html',
  '/app_bootstrap.js',
  '/manifest.json',
  '/favicon.png',
  '/icons/Icon-192.png',
  '/icons/Icon-512.png',
  '/icons/Icon-maskable-192.png',
  '/icons/Icon-maskable-512.png',
]
const SAFE_FILES = new Set([
  '/app_bootstrap.js',
  '/favicon.png',
  '/flutter.js',
  '/flutter_bootstrap.js',
  '/index.html',
  '/main.dart.js',
  '/manifest.json',
  '/version.json',
])
const SAFE_PREFIXES = ['/assets/', '/canvaskit/', '/icons/']

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_ASSETS))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter(
              (key) =>
                key !== CACHE_NAME &&
                MANAGED_CACHE_PREFIXES.some((prefix) => key.startsWith(prefix)),
            )
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  )
})

function isSafeShellRequest(request) {
  if (request.method !== 'GET') return false

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return false
  if (url.pathname === '/api' || url.pathname.startsWith('/api/')) return false

  return (
    request.mode === 'navigate' ||
    SAFE_FILES.has(url.pathname) ||
    SAFE_PREFIXES.some((prefix) => url.pathname.startsWith(prefix))
  )
}

async function storeSuccessfulResponse(cache, cacheKey, response) {
  if (!response.ok || response.type !== 'basic') return response

  await cache.put(cacheKey, response.clone())
  return response
}

async function networkFirst(request, cacheKey = request, fallbackPath = null) {
  const cache = await caches.open(CACHE_NAME)

  try {
    const response = await fetch(request, { cache: 'no-store' })
    return await storeSuccessfulResponse(cache, cacheKey, response)
  } catch {
    const cached = await cache.match(cacheKey)
    if (cached) return cached
    if (fallbackPath !== null) {
      return (await cache.match(fallbackPath)) ?? Response.error()
    }
    return Response.error()
  }
}

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (!isSafeShellRequest(request)) return

  if (request.mode === 'navigate') {
    event.respondWith(networkFirst(request, '/index.html', '/index.html'))
    return
  }

  event.respondWith(networkFirst(request))
})
