/* global fetch */

import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import {
  cacheControlFor,
  contentTypeFor,
  createStaticServer,
  resolveRequestPath,
} from './server.mjs'

test('static path resolution remains inside the distribution root', () => {
  const root = '/tmp/meufinanceiro-dist'
  assert.equal(resolveRequestPath(root, '/assets/app.js'), join(root, 'assets/app.js'))
  assert.equal(resolveRequestPath(root, '/../secret'), null)
  assert.equal(resolveRequestPath(root, '/%2e%2e/secret'), null)
  assert.equal(resolveRequestPath(root, '/%E0%A4%A'), null)
})

test('static response metadata is conservative', () => {
  assert.equal(contentTypeFor('/assets/app.js'), 'text/javascript; charset=utf-8')
  assert.equal(contentTypeFor('/manifest.webmanifest'), 'application/manifest+json; charset=utf-8')
  assert.equal(cacheControlFor('/assets/app.js'), 'public, max-age=31536000, immutable')
  assert.equal(cacheControlFor('/sw.js'), 'no-cache')
})

test('server provides SPA fallback without exposing arbitrary methods', async (context) => {
  const root = await mkdtemp(join(tmpdir(), 'meufinanceiro-web-'))
  context.after(() => rm(root, { recursive: true, force: true }))
  await writeFile(join(root, 'index.html'), '<main>MeuFinanceiro</main>')

  const server = createStaticServer({ root })
  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolve)
  })
  context.after(() => new Promise((resolve) => server.close(resolve)))

  const address = server.address()
  assert.ok(address && typeof address === 'object')
  const baseUrl = `http://127.0.0.1:${address.port}`

  const rootResponse = await fetch(baseUrl)
  assert.equal(rootResponse.status, 200)

  const navigation = await fetch(`${baseUrl}/componentes`)
  assert.equal(navigation.status, 200)
  assert.match(await navigation.text(), /MeuFinanceiro/)

  const missingAsset = await fetch(`${baseUrl}/assets/missing.js`)
  assert.equal(missingAsset.status, 404)

  const mutation = await fetch(baseUrl, { method: 'POST' })
  assert.equal(mutation.status, 405)
  assert.equal(mutation.headers.get('allow'), 'GET, HEAD')
})
