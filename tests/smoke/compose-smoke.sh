#!/usr/bin/env sh
set -eu

BASE_URL="${BASE_URL:-http://127.0.0.1:${APP_HTTP_PORT:-8080}}"
ATTEMPTS="${SMOKE_ATTEMPTS:-60}"

attempt=1
while [ "$attempt" -le "$ATTEMPTS" ]; do
  if curl --fail --silent --show-error "$BASE_URL/api/v1/health/ready" | grep -q '"schema":"ok"' \
    && curl --fail --silent --show-error "$BASE_URL/" | grep -q 'id="root"' \
    && curl --fail --silent --show-error "$BASE_URL/componentes" | grep -q 'id="root"' \
    && curl --fail --silent --show-error "$BASE_URL/manifest.webmanifest" | grep -q '"display": "standalone"' \
    && curl --fail --silent --show-error "$BASE_URL/sw.js" | grep -q "pathname.startsWith('/api/')" \
    && docker compose exec -T worker python -c \
      "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health/ready', timeout=2)"; then
    break
  fi
  sleep 2
  attempt=$((attempt + 1))
done

if [ "$attempt" -gt "$ATTEMPTS" ]; then
  printf 'Smoke test failed after %s attempts: %s\n' "$ATTEMPTS" "$BASE_URL" >&2
  exit 1
fi

IDEMPOTENCY_KEY="smoke-$(date +%s)-$$"
FIRST=$(docker compose exec -T api python -m meufinanceiro_persistence.cli \
  enqueue-demo --idempotency-key "$IDEMPOTENCY_KEY")
SECOND=$(docker compose exec -T api python -m meufinanceiro_persistence.cli \
  enqueue-demo --idempotency-key "$IDEMPOTENCY_KEY")
FIRST_ID=$(printf '%s' "$FIRST" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
SECOND_ID=$(printf '%s' "$SECOND" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

if [ "$FIRST_ID" != "$SECOND_ID" ]; then
  echo "Idempotency smoke check returned different task IDs." >&2
  exit 1
fi

attempt=1
while [ "$attempt" -le "$ATTEMPTS" ]; do
  TASK=$(docker compose exec -T api python -m meufinanceiro_persistence.cli \
    get --task-id "$FIRST_ID")
  STATUS=$(printf '%s' "$TASK" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')
  if [ "$STATUS" = "succeeded" ]; then
    printf 'Smoke test passed: %s task=%s\n' "$BASE_URL" "$FIRST_ID"
    exit 0
  fi
  sleep 1
  attempt=$((attempt + 1))
done

printf 'Worker did not complete smoke task %s.\n' "$FIRST_ID" >&2
exit 1
