import assert from 'node:assert/strict'
import test from 'node:test'

import { apiStateFromResponse, readinessFromPayload } from './api-status.ts'

test('maps readiness responses without hiding degraded services', () => {
  assert.equal(apiStateFromResponse(true, { status: 'ok' }), 'online')
  assert.equal(apiStateFromResponse(true, { status: 'degraded' }), 'degraded')
  assert.equal(apiStateFromResponse(false, { status: 'degraded' }), 'degraded')
  assert.equal(apiStateFromResponse(false, { detail: 'unavailable' }), 'offline')
})

test('normalizes the public readiness contract defensively', () => {
  assert.deepEqual(
    readinessFromPayload({
      status: 'degraded',
      process: 'ok',
      database: 'unavailable',
      schema: 'outdated',
      current_revision: 'abc',
      expected_revision: 'def',
    }),
    {
      status: 'degraded',
      process: 'ok',
      database: 'unavailable',
      schema: 'outdated',
      currentRevision: 'abc',
      expectedRevision: 'def',
    },
  )
})

test('uses unknown values for malformed payloads', () => {
  const result = readinessFromPayload({ status: 200, database: true })
  assert.equal(result.status, 'unknown')
  assert.equal(result.database, 'unknown')
})
