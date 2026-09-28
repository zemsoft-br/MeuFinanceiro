import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

const ORIGIN = 'http://localhost:8080'
const CURRENT_CACHE = 'meufinanceiro-flutter-shell-v1'
const source = readFileSync('apps/app/web/sw.js', 'utf8')

function normalizeCacheKey(input) {
  const raw = typeof input === 'string' ? input : input.url
  const url = new URL(raw, ORIGIN)
  return `${url.pathname}${url.search}`
}

function createResponse(body) {
  return {
    body,
    ok: true,
    type: 'basic',
    clone() {
      return createResponse(body)
    },
  }
}

class FakeCache {
  constructor() {
    this.entries = new Map()
    this.precached = []
  }

  async addAll(paths) {
    this.precached = [...paths]
    for (const path of paths) {
      this.entries.set(normalizeCacheKey(path), createResponse(`precache:${path}`))
    }
  }

  async put(key, response) {
    this.entries.set(normalizeCacheKey(key), response)
  }

  async match(key) {
    return this.entries.get(normalizeCacheKey(key))
  }
}

function createRuntime({ fetchImpl } = {}) {
  const listeners = new Map()
  const stores = new Map()
  const deleted = []
  let claimed = false
  let skippedWaiting = false

  const caches = {
    async open(name) {
      if (!stores.has(name)) stores.set(name, new FakeCache())
      return stores.get(name)
    },
    async keys() {
      return [...stores.keys()]
    },
    async delete(name) {
      deleted.push(name)
      return stores.delete(name)
    },
  }

  const self = {
    location: { origin: ORIGIN },
    clients: {
      async claim() {
        claimed = true
      },
    },
    addEventListener(type, listener) {
      listeners.set(type, listener)
    },
    async skipWaiting() {
      skippedWaiting = true
    },
  }

  vm.runInNewContext(source, {
    Response: { error: () => ({ error: true }) },
    URL,
    caches,
    fetch:
      fetchImpl ??
      (async (request) => createResponse(`network:${normalizeCacheKey(request)}`)),
    self,
  })

  return {
    deleted,
    get claimed() {
      return claimed
    },
    get skippedWaiting() {
      return skippedWaiting
    },
    listeners,
    stores,
  }
}

function createLifecycleEvent() {
  let completion
  return {
    event: {
      waitUntil(promise) {
        completion = Promise.resolve(promise)
      },
    },
    async completed() {
      assert.ok(completion, 'waitUntil must receive the lifecycle promise')
      await completion
    },
  }
}

function createFetchEvent(request) {
  let response
  return {
    event: {
      request,
      respondWith(promise) {
        response = Promise.resolve(promise)
      },
    },
    get response() {
      return response
    },
  }
}

function request(path, { method = 'GET', mode = 'same-origin', origin = ORIGIN } = {}) {
  return {
    method,
    mode,
    url: new URL(path, origin).toString(),
  }
}

test('never intercepts the exact API root or API subpaths', () => {
  const runtime = createRuntime()

  for (const path of ['/api', '/api/v1/health/ready']) {
    const fetchEvent = createFetchEvent(request(path, { mode: 'navigate' }))
    runtime.listeners.get('fetch')(fetchEvent.event)
    assert.equal(fetchEvent.response, undefined, `${path} must bypass respondWith`)
  }
})

test('never intercepts non-GET or cross-origin requests', () => {
  const runtime = createRuntime()
  const scenarios = [
    request('/componentes', { method: 'POST', mode: 'navigate' }),
    request('/main.dart.js', { origin: 'https://example.invalid' }),
  ]

  for (const candidate of scenarios) {
    const fetchEvent = createFetchEvent(candidate)
    runtime.listeners.get('fetch')(fetchEvent.event)
    assert.equal(fetchEvent.response, undefined)
  }
})

test('normalizes successful navigation responses to index.html', async () => {
  const runtime = createRuntime()
  const fetchEvent = createFetchEvent(request('/componentes', { mode: 'navigate' }))

  runtime.listeners.get('fetch')(fetchEvent.event)
  const response = await fetchEvent.response
  const cache = runtime.stores.get(CURRENT_CACHE)

  assert.equal(response.body, 'network:/componentes')
  assert.ok(cache.entries.has('/index.html'))
  assert.equal(cache.entries.has('/componentes'), false)
})

test('uses only the app cache for an offline navigation fallback', async () => {
  const runtime = createRuntime({
    fetchImpl: async () => {
      throw new Error('offline')
    },
  })
  const appCache = new FakeCache()
  const unrelatedCache = new FakeCache()
  appCache.entries.set('/index.html', createResponse('trusted-shell'))
  unrelatedCache.entries.set('/componentes', createResponse('unrelated-entry'))
  runtime.stores.set(CURRENT_CACHE, appCache)
  runtime.stores.set('another-application', unrelatedCache)

  const fetchEvent = createFetchEvent(request('/componentes', { mode: 'navigate' }))
  runtime.listeners.get('fetch')(fetchEvent.event)
  const response = await fetchEvent.response

  assert.equal(response.body, 'trusted-shell')
})

test('deletes old Flutter and legacy React caches on activation', async () => {
  const runtime = createRuntime()
  runtime.stores.set(CURRENT_CACHE, new FakeCache())
  runtime.stores.set('meufinanceiro-flutter-shell-v0', new FakeCache())
  runtime.stores.set('meufinanceiro-shell-v3', new FakeCache())
  runtime.stores.set('another-application', new FakeCache())

  const lifecycle = createLifecycleEvent()
  runtime.listeners.get('activate')(lifecycle.event)
  await lifecycle.completed()

  assert.deepEqual(
    new Set(runtime.deleted),
    new Set(['meufinanceiro-flutter-shell-v0', 'meufinanceiro-shell-v3']),
  )
  assert.equal(runtime.stores.has(CURRENT_CACHE), true)
  assert.equal(runtime.stores.has('another-application'), true)
  assert.equal(runtime.claimed, true)
})

test('completes the minimal precache before activation is requested', async () => {
  const runtime = createRuntime()
  const lifecycle = createLifecycleEvent()

  runtime.listeners.get('install')(lifecycle.event)
  assert.equal(runtime.skippedWaiting, false)
  await lifecycle.completed()

  const cache = runtime.stores.get(CURRENT_CACHE)
  assert.ok(cache.precached.includes('/index.html'))
  assert.ok(cache.precached.includes('/app_bootstrap.js'))
  assert.equal(cache.precached.includes('/sw.js'), false)
  assert.equal(runtime.skippedWaiting, true)
})
