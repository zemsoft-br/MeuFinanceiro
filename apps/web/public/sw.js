const SHELL_CACHE = 'meufinanceiro-shell-v1'
const SHELL_ASSETS = [
  '/',
  '/index.html',
  '/manifest.webmanifest',
  '/favicon.svg',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
]
const SAFE_PATHS = new Set(['/index.html', '/manifest.webmanifest', '/favicon.svg', '/sw.js'])
const SAFE_PREFIXES = ['/assets/', '/icons/']

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_ASSETS)))
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key.startsWith('meufinanceiro-shell-') && key !== SHELL_CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  )
})

function isSafeShellRequest(request) {
  if (request.method !== 'GET') return false

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return false
  if (url.pathname.startsWith('/api/')) return false

  return (
    request.mode === 'navigate' ||
    SAFE_PATHS.has(url.pathname) ||
    SAFE_PREFIXES.some((prefix) => url.pathname.startsWith(prefix))
  )
}

async function networkFirstNavigation(request) {
  try {
    return await fetch(request)
  } catch {
    return (await caches.match('/index.html')) ?? Response.error()
  }
}

async function cacheFirstAsset(request) {
  const cached = await caches.match(request)
  if (cached) return cached

  const response = await fetch(request)
  if (response.ok && response.type === 'basic') {
    const cache = await caches.open(SHELL_CACHE)
    await cache.put(request, response.clone())
  }
  return response
}

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (!isSafeShellRequest(request)) return

  if (request.mode === 'navigate') {
    event.respondWith(networkFirstNavigation(request))
    return
  }

  event.respondWith(cacheFirstAsset(request))
})
