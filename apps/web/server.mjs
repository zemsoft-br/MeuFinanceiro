/* global Buffer, URL, process */

import { readFile, stat } from 'node:fs/promises'
import { createServer } from 'node:http'
import { extname, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const DEFAULT_ROOT = resolve(fileURLToPath(new URL('./dist/', import.meta.url)))
const DEFAULT_PORT = 5173

const CONTENT_TYPES = new Map([
  ['.css', 'text/css; charset=utf-8'],
  ['.html', 'text/html; charset=utf-8'],
  ['.js', 'text/javascript; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'],
  ['.png', 'image/png'],
  ['.svg', 'image/svg+xml; charset=utf-8'],
  ['.webmanifest', 'application/manifest+json; charset=utf-8'],
  ['.woff2', 'font/woff2'],
])

export function resolveRequestPath(root, pathname) {
  let decodedPath
  try {
    decodedPath = decodeURIComponent(pathname)
  } catch {
    return null
  }

  const relativePath = decodedPath.replace(/^\/+/, '')
  const candidate = resolve(root, relativePath)
  if (candidate !== root && !candidate.startsWith(`${root}${sep}`)) return null
  return candidate
}

export function contentTypeFor(pathname) {
  return CONTENT_TYPES.get(extname(pathname).toLowerCase()) ?? 'application/octet-stream'
}

export function cacheControlFor(pathname) {
  if (pathname.startsWith('/assets/')) return 'public, max-age=31536000, immutable'
  return 'no-cache'
}

async function existingFile(pathname) {
  try {
    const metadata = await stat(pathname)
    return metadata.isFile() ? pathname : null
  } catch {
    return null
  }
}

function sendText(response, statusCode, message) {
  const body = Buffer.from(message)
  response.writeHead(statusCode, {
    'Cache-Control': 'no-store',
    'Content-Length': body.byteLength,
    'Content-Type': 'text/plain; charset=utf-8',
  })
  response.end(body)
}

export function createStaticServer({ root = DEFAULT_ROOT } = {}) {
  const normalizedRoot = resolve(root)

  return createServer(async (request, response) => {
    try {
      if (request.method !== 'GET' && request.method !== 'HEAD') {
        response.setHeader('Allow', 'GET, HEAD')
        sendText(response, 405, 'Method not allowed')
        return
      }

      const url = new URL(request.url ?? '/', 'http://localhost')
      const requestedPath = resolveRequestPath(normalizedRoot, url.pathname)
      if (!requestedPath) {
        sendText(response, 400, 'Invalid path')
        return
      }

      let filePath = await existingFile(requestedPath)
      const acceptsHtml = request.headers.accept?.includes('text/html') ?? false
      const isRoutePath = url.pathname === '/' || extname(url.pathname) === ''
      if (!filePath && (acceptsHtml || isRoutePath)) {
        filePath = await existingFile(resolve(normalizedRoot, 'index.html'))
      }
      if (!filePath) {
        sendText(response, 404, 'Not found')
        return
      }

      const body = await readFile(filePath)
      response.writeHead(200, {
        'Cache-Control': cacheControlFor(url.pathname),
        'Content-Length': body.byteLength,
        'Content-Type': contentTypeFor(filePath),
        'X-Content-Type-Options': 'nosniff',
      })
      response.end(request.method === 'HEAD' ? undefined : body)
    } catch {
      sendText(response, 500, 'Internal server error')
    }
  })
}

function start() {
  const parsedPort = Number(process.env.PORT ?? DEFAULT_PORT)
  if (!Number.isInteger(parsedPort) || parsedPort < 1 || parsedPort > 65535) {
    throw new Error('PORT must be an integer between 1 and 65535')
  }

  const server = createStaticServer()
  server.listen(parsedPort, '0.0.0.0', () => {
    process.stdout.write(`MeuFinanceiro Web listening on ${parsedPort}\n`)
  })

  const shutdown = () => {
    server.close((error) => {
      process.exitCode = error ? 1 : 0
    })
  }
  process.once('SIGINT', shutdown)
  process.once('SIGTERM', shutdown)
}

const entrypoint = process.argv[1] ? resolve(process.argv[1]) : null
if (entrypoint === fileURLToPath(import.meta.url)) start()
