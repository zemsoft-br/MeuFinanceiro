import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const responsiveStylesUrl = new URL('./responsive-shell.css', import.meta.url)

test('mobile menu controls remain hidden outside the supported mobile breakpoint', async () => {
  const source = await readFile(responsiveStylesUrl, 'utf8')

  assert.match(
    source,
    /\.icon-button\.sidebar__close,[\s\S]*\.icon-button\.topbar__menu\s*\{\s*display:\s*none;/,
  )
  assert.match(
    source,
    /@media\s*\(max-width:\s*820px\)[\s\S]*\.icon-button\.sidebar__close,[\s\S]*\.icon-button\.topbar__menu\s*\{\s*display:\s*inline-grid;/,
  )
})
