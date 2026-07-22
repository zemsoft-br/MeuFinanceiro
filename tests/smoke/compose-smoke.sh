#!/usr/bin/env sh
set -eu

BASE_URL="${BASE_URL:-http://127.0.0.1:${APP_HTTP_PORT:-8080}}"
ATTEMPTS="${SMOKE_ATTEMPTS:-60}"

header_contains() {
  url="$1"
  pattern="$2"
  curl --fail --silent --show-error --head "$url" \
    | tr -d '\r' \
    | grep -Eiq "^Cache-Control: .*${pattern}"
}

status_is() {
  url="$1"
  expected="$2"
  actual="$(curl --silent --output /dev/null --write-out '%{http_code}' "$url")"
  [ "$actual" = "$expected" ]
}

flutter_runtime_ok() {
  curl --fail --silent --show-error "$BASE_URL/" | grep -q 'app_bootstrap.js' \
    && curl --fail --silent --show-error "$BASE_URL/componentes" | grep -q 'app_bootstrap.js' \
    && curl --fail --silent --show-error "$BASE_URL/sistema" | grep -q 'app_bootstrap.js' \
    && curl --fail --silent --show-error "$BASE_URL/app_bootstrap.js" | grep -q "script.src = 'flutter_bootstrap.js'" \
    && curl --fail --silent --show-error "$BASE_URL/app_bootstrap.js" | grep -q "register('sw.js'" \
    && curl --fail --silent --show-error "$BASE_URL/manifest.json" | grep -q '"display": "standalone"' \
    && curl --fail --silent --show-error "$BASE_URL/sw.js" | grep -q "pathname.startsWith('/api/')" \
    && header_contains "$BASE_URL/index.html" "no-store" \
    && header_contains "$BASE_URL/app_bootstrap.js" "no-store" \
    && header_contains "$BASE_URL/sw.js" "no-store" \
    && header_contains "$BASE_URL/main.dart.js" "no-store" \
    && header_contains "$BASE_URL/assets/AssetManifest.bin" "max-age=3600" \
    && status_is "$BASE_URL/assets/does-not-exist.js" "404"
}

attempt=1
while [ "$attempt" -le "$ATTEMPTS" ]; do
  if curl --fail --silent --show-error "$BASE_URL/api/v1/health/ready" | grep -q '"schema":"ok"' \
    && status_is "$BASE_URL/api" "404" \
    && flutter_runtime_ok \
    && docker compose exec -T web sh -c 'test "$(id -u)" -ne 0' \
    && docker compose exec -T worker python -c \
      "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health/ready', timeout=2)"; then
    break
  fi
  sleep 2
  attempt=$((attempt + 1))
done

if [ "$attempt" -gt "$ATTEMPTS" ]; then
  printf 'Flutter Web smoke test failed after %s attempts: %s\n' \
    "$ATTEMPTS" "$BASE_URL" >&2
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
    printf 'Flutter Web smoke test passed: %s task=%s\n' \
      "$BASE_URL" "$FIRST_ID"
    exit 0
  fi
  sleep 1
  attempt=$((attempt + 1))
done

printf 'Worker did not complete smoke task %s.\n' "$FIRST_ID" >&2
exit 1
