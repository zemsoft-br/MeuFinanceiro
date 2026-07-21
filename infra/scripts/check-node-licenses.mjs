#!/usr/bin/env node

import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

export function npmQueryInvocation({
  platform = process.platform,
  comSpec = process.env.ComSpec,
} = {}) {
  if (platform === 'win32') {
    return {
      command: comSpec || 'cmd.exe',
      args: ['/d', '/s', '/c', 'npm.cmd query * --json'],
    }
  }

  return {
    command: 'npm',
    args: ['query', '*', '--json'],
  }
}

export function queryInstalledPackages(
  workingDirectory,
  { platform, comSpec, spawn = spawnSync } = {},
) {
  const invocation = npmQueryInvocation({ platform, comSpec })
  return spawn(invocation.command, invocation.args, {
    cwd: workingDirectory,
    encoding: 'utf8',
  })
}

function main() {
  const workingDirectory = process.argv[2] ?? 'apps/web'
  const result = queryInstalledPackages(workingDirectory)

  if (result.status !== 0) {
    console.error(result.stderr || result.error?.message || 'npm query failed')
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
}

const entrypoint = process.argv[1] ? resolve(process.argv[1]) : null
if (entrypoint === fileURLToPath(import.meta.url)) main()
