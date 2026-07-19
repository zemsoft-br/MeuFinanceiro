import assert from 'node:assert/strict'
import test from 'node:test'

import { apiStateFromResponse } from './api-status.ts'

test('maps successful readiness responses to online', () => {
  assert.equal(apiStateFromResponse(true), 'online')
})

test('maps failed readiness responses to offline', () => {
  assert.equal(apiStateFromResponse(false), 'offline')
})
