import assert from 'node:assert/strict'
import test from 'node:test'

import {
  npmQueryInvocation,
  queryInstalledPackages,
} from '../../infra/scripts/check-node-licenses.mjs'

test('uses npm directly on POSIX platforms', () => {
  assert.deepEqual(npmQueryInvocation({ platform: 'linux' }), {
    command: 'npm',
    args: ['query', '*', '--json'],
  })
})

test('uses cmd and npm.cmd on Windows', () => {
  assert.deepEqual(
    npmQueryInvocation({
      platform: 'win32',
      comSpec: 'C:\\Windows\\System32\\cmd.exe',
    }),
    {
      command: 'C:\\Windows\\System32\\cmd.exe',
      args: ['/d', '/s', '/c', 'npm.cmd query "*" --json'],
    },
  )
})

test('passes the selected command and working directory to spawn', () => {
  const calls = []
  const result = queryInstalledPackages('apps/web', {
    platform: 'win32',
    comSpec: 'cmd.exe',
    spawn(command, args, options) {
      calls.push({ command, args, options })
      return { status: 0, stdout: '[]', stderr: '' }
    },
  })

  assert.equal(result.status, 0)
  assert.deepEqual(calls, [
    {
      command: 'cmd.exe',
      args: ['/d', '/s', '/c', 'npm.cmd query "*" --json'],
      options: { cwd: 'apps/web', encoding: 'utf8' },
    },
  ])
})
