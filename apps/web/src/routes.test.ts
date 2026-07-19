import assert from 'node:assert/strict'
import test from 'node:test'

import { isInternalNavigation, normalizePath, routeFromPath } from './routes.ts'

test('normalizes known application paths', () => {
  assert.equal(normalizePath('//componentes/?tab=buttons'), '/componentes')
  assert.equal(routeFromPath('/sistema/').id, 'system')
})

test('falls back safely for unknown paths', () => {
  assert.equal(routeFromPath('/rota-inexistente').id, 'home')
})

test('keeps API and external URLs outside client routing', () => {
  assert.equal(isInternalNavigation('/componentes'), true)
  assert.equal(isInternalNavigation('/api/v1/docs'), false)
  assert.equal(isInternalNavigation('//example.test'), false)
  assert.equal(isInternalNavigation('https://example.test'), false)
})
