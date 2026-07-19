import assert from 'node:assert/strict'
import test from 'node:test'

import { hasValidationErrors, validateDemoPreferences } from './validation.ts'

test('requires a meaningful residence name', () => {
  assert.equal(validateDemoPreferences({ residenceName: '', startDay: '1' }).residenceName !== undefined, true)
  assert.equal(validateDemoPreferences({ residenceName: 'Ip', startDay: '1' }).residenceName !== undefined, true)
  assert.equal(validateDemoPreferences({ residenceName: 'Residência Ipê', startDay: '1' }).residenceName, undefined)
})

test('accepts only supported cycle days', () => {
  assert.equal(validateDemoPreferences({ residenceName: 'Casa', startDay: '0' }).startDay !== undefined, true)
  assert.equal(validateDemoPreferences({ residenceName: 'Casa', startDay: '28' }).startDay, undefined)
  assert.equal(validateDemoPreferences({ residenceName: 'Casa', startDay: '29' }).startDay !== undefined, true)
})

test('reports whether validation produced errors', () => {
  assert.equal(hasValidationErrors({}), false)
  assert.equal(hasValidationErrors({ startDay: 'inválido' }), true)
})
