import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const tokensUrl = new URL('./tokens.css', import.meta.url)
const stylesUrl = new URL('./styles.css', import.meta.url)
const componentsUrl = new URL('./components.css', import.meta.url)

function parseHexTokens(source: string): Map<string, string> {
  return new Map(
    Array.from(source.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6});/gi), (match) => [match[1], match[2]]),
  )
}

function relativeLuminance(hex: string): number {
  const channels = [hex.slice(1, 3), hex.slice(3, 5), hex.slice(5, 7)].map(
    (channel) => Number.parseInt(channel, 16) / 255,
  )
  const [red, green, blue] = channels.map((value) =>
    value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4,
  )
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue
}

function contrast(foreground: string, background: string): number {
  const values = [relativeLuminance(foreground), relativeLuminance(background)].sort(
    (left, right) => right - left,
  )
  return (values[0] + 0.05) / (values[1] + 0.05)
}

test('small text token pairs meet WCAG AA contrast', async () => {
  const tokens = parseHexTokens(await readFile(tokensUrl, 'utf8'))
  const pairs = [
    ['color-brand-700', 'color-surface'],
    ['color-ink-600', 'color-surface'],
    ['color-ink-500', 'color-surface'],
    ['color-ink-500', 'color-canvas'],
    ['color-positive-700', 'color-positive-100'],
    ['color-warning-700', 'color-warning-100'],
    ['color-negative-700', 'color-negative-100'],
    ['color-info-700', 'color-info-100'],
  ] as const

  for (const [foregroundName, backgroundName] of pairs) {
    const foreground = tokens.get(foregroundName)
    const background = tokens.get(backgroundName)
    assert.ok(foreground && background, `missing color pair ${foregroundName}/${backgroundName}`)
    assert.ok(
      contrast(foreground, background) >= 4.5,
      `${foregroundName} does not meet 4.5:1 on ${backgroundName}`,
    )
  }
})

test('interaction styles preserve keyboard focus and reduced motion', async () => {
  const source = `${await readFile(stylesUrl, 'utf8')}\n${await readFile(componentsUrl, 'utf8')}`
  assert.match(source, /:focus-visible/)
  assert.match(source, /prefers-reduced-motion:\s*reduce/)
  assert.match(source, /\.skip-link:focus/)
})
