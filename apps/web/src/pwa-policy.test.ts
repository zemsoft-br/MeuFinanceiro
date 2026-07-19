import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const serviceWorkerUrl = new URL('../public/sw.js', import.meta.url)
const manifestUrl = new URL('../public/manifest.webmanifest', import.meta.url)

test('service worker uses a versioned shell cache and excludes API traffic', async () => {
  const source = await readFile(serviceWorkerUrl, 'utf8')
  assert.match(source, /meufinanceiro-shell-v\d+/)
  assert.match(source, /pathname\.startsWith\('\/api\/'\)/)
  assert.match(source, /request\.method !== 'GET'/)
  assert.doesNotMatch(source, /caches\.match\(request\).*api/s)
})

test('manifest declares standalone mode and install icons', async () => {
  const manifest = JSON.parse(await readFile(manifestUrl, 'utf8')) as {
    display?: string
    icons?: { sizes?: string }[]
  }
  assert.equal(manifest.display, 'standalone')
  assert.deepEqual(manifest.icons?.map((icon) => icon.sizes), ['192x192', '512x512'])
})
