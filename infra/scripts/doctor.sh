#!/usr/bin/env sh
set -eu

status=0
for command_name in docker curl; do
  if command -v "$command_name" >/dev/null 2>&1; then
    printf 'OK   %s\n' "$command_name"
  else
    printf 'FAIL %s não encontrado\n' "$command_name" >&2
    status=1
  fi
done

if command -v docker >/dev/null 2>&1; then
  if docker compose version >/dev/null 2>&1; then
    printf 'OK   docker compose v2\n'
  else
    printf 'FAIL docker compose v2 não encontrado\n' >&2
    status=1
  fi
fi

exit "$status"
