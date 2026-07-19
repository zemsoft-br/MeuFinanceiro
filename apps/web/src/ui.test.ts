import assert from 'node:assert/strict'
import test from 'node:test'
import { renderToStaticMarkup } from 'react-dom/server'

import { Badge, Button, StatePanel } from './ui.ts'

test('button defaults to a non-submitting accessible action', () => {
  const html = renderToStaticMarkup(Button({ children: 'Continuar' }))
  assert.match(html, /type="button"/)
  assert.match(html, /button--primary/)
  assert.match(html, />Continuar</)
})

test('badge exposes both text and semantic tone class', () => {
  const html = renderToStaticMarkup(Badge({ tone: 'positive', children: 'Concluído' }))
  assert.match(html, /badge--positive/)
  assert.match(html, />Concluído</)
})

test('loading panel declares busy state without hiding its text', () => {
  const html = renderToStaticMarkup(
    StatePanel({ kind: 'loading', title: 'Carregando', description: 'Aguarde.' }),
  )
  assert.match(html, /aria-busy="true"/)
  assert.match(html, />Carregando</)
  assert.match(html, />Aguarde\.</)
})
