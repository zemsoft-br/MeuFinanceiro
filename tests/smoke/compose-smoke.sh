#!/usr/bin/env sh
set -eu

BASE_URL="${BASE_URL:-http://127.0.0.1:${APP_HTTP_PORT:-8080}}"
ATTEMPTS="${SMOKE_ATTEMPTS:-60}"

attempt=1
while [ "$attempt" -le "$ATTEMPTS" ]; do
  if curl --fail --silent --show-error "$BASE_URL/api/v1/health/ready" >/dev/null \
    && curl --fail --silent --show-error "$BASE_URL/" >/dev/null; then
    printf 'Smoke test passed: %s\n' "$BASE_URL"
    exit 0
  fi

  sleep 2
  attempt=$((attempt + 1))
done

printf 'Smoke test failed after %s attempts: %s\n' "$ATTEMPTS" "$BASE_URL" >&2
exit 1
