#!/usr/bin/env node

import { spawnSync } from 'node:child_process'
import process from 'node:process'

const workingDirectory = process.argv[2] ?? 'apps/web'
const result = spawnSync('npm', ['query', '.', '--json'], {
  cwd: workingDirectory,
  encoding: 'utf8',
})

if (result.status !== 0) {
  console.error(result.stderr || 'npm query failed')
  process.exit(2)
}

const packages = JSON.parse(result.stdout)
const denied = /GPL-2\.0-only|SSPL|BUSL|Business Source License|Commons Clause|Elastic License|PolyForm/i
const failures = []

for (const packageInfo of packages) {
  if (packageInfo.private === true) continue
  const name = packageInfo.name ?? 'UNKNOWN'
  const version = packageInfo.version ?? 'UNKNOWN'
  const license = packageInfo.license ?? 'UNKNOWN'
  console.log(`${name}@${version}\t${license}`)
  if (denied.test(String(license))) {
    failures.push(`${name}@${version}: ${license}`)
  }
}

if (failures.length > 0) {
  console.error('Known incompatible or review-required Node licenses detected:')
  for (const failure of failures) console.error(`- ${failure}`)
  process.exit(1)
}
