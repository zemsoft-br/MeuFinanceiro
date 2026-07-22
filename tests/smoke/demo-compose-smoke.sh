#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
ENV_FILE=${DEMO_ENV_FILE:-$ROOT_DIR/.demo/.env}
PROJECT_NAME=${DEMO_PROJECT_NAME:-meufinanceiro-demo}

PORT=$(awk -F= '$1 == "APP_HTTP_PORT" {print $2}' "$ENV_FILE" | tail -n 1)
PORT=${PORT:-8081}
BASE_URL="http://127.0.0.1:$PORT"

compose() {
  docker compose \
    --project-name "$PROJECT_NAME" \
    --env-file "$ENV_FILE" \
    --profile demo \
    "$@"
}

status_json() {
  python3 - "$BASE_URL/api/v1/demo/status" <<'PY'
import sys
import urllib.request

with urllib.request.urlopen(sys.argv[1], timeout=3) as response:
    sys.stdout.write(response.read().decode("utf-8"))
PY
}

status_json | python3 -c '
import json, sys
payload = json.load(sys.stdin)
assert payload["enabled"] is True
assert payload["loaded"] is True
assert payload["fixture_id"] == "residencia-ipe-v1"
assert payload["fixture_version"] == 1
assert payload["reference_date"] == "2026-11-01"
assert payload["timezone"] == "America/Sao_Paulo"
assert payload["currency"] == "BRL"
assert payload["scope"] == "foundation_only"
assert len(payload["contract_checksum"]) == 64
'

TASK_JSON=$(compose exec -T api python -m meufinanceiro_persistence.cli \
  enqueue-demo --idempotency-key demo-fixture-isolation-smoke)
TASK_ID=$(printf '%s' "$TASK_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

compose run --rm demo-fixture \
  python -m meufinanceiro_persistence.demo_cli reset >/dev/null
status_json | python3 -c '
import json, sys
payload = json.load(sys.stdin)
assert payload["enabled"] is True
assert payload["loaded"] is False
'

SECOND_RESET=$(compose run --rm demo-fixture \
  python -m meufinanceiro_persistence.demo_cli reset)
printf '%s' "$SECOND_RESET" | python3 -c '
import json, sys
payload = json.load(sys.stdin)
assert payload["fixture_id"] == "residencia-ipe-v1"
assert payload["removed"] is False
'

compose exec -T api python -m meufinanceiro_persistence.cli \
  get --task-id "$TASK_ID" >/dev/null

FIRST_LOAD=$(compose run --rm demo-fixture \
  python -m meufinanceiro_persistence.demo_cli load)
SECOND_LOAD=$(compose run --rm demo-fixture \
  python -m meufinanceiro_persistence.demo_cli load)
python3 - "$FIRST_LOAD" "$SECOND_LOAD" <<'PY'
import json
import sys

first = json.loads(sys.argv[1])
second = json.loads(sys.argv[2])
assert first == second
assert first["loaded"] is True
assert first["fixture_id"] == "residencia-ipe-v1"
PY

status_json | python3 -c '
import json, sys
payload = json.load(sys.stdin)
assert payload["enabled"] is True
assert payload["loaded"] is True
'

echo "Demo Compose smoke passed."
