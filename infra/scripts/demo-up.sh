#!/usr/bin/env sh
set -eu

ACTION=${1:-up}
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
STATE_DIR="$ROOT_DIR/.demo"
SECRETS_DIR="$STATE_DIR/secrets"
ENV_FILE="$STATE_DIR/.env"
KEYRING_FILE="$SECRETS_DIR/keyring.json"
OPERATOR_PASSWORD_FILE="$SECRETS_DIR/operator_password.txt"
PROJECT_NAME="meufinanceiro-demo"

case "$ACTION" in
  up|load|status|reset|down|purge) ;;
  *)
    echo "Uso: $0 [up|load|status|reset|down|purge]" >&2
    exit 2
    ;;
esac

command -v docker >/dev/null 2>&1 || {
  echo "Docker não encontrado." >&2
  exit 1
}
command -v python3 >/dev/null 2>&1 || {
  echo "Python 3 é necessário para gerar a configuração demo." >&2
  exit 1
}
docker compose version >/dev/null 2>&1 || {
  echo "Docker Compose v2 não encontrado." >&2
  exit 1
}

generate_password() {
  python3 -c 'import secrets; print(secrets.token_hex(24))'
}

migrate_legacy_operator_password() {
  legacy_count=$(grep -c '^DEMO_OPERATOR_PASSWORD=' "$ENV_FILE" || true)
  if [ "$legacy_count" -eq 0 ]; then
    unset legacy_count
    return
  fi
  if [ "$legacy_count" -ne 1 ]; then
    echo "A configuração demo contém múltiplas credenciais legadas; nenhuma fonte foi alterada." >&2
    unset legacy_count
    exit 1
  fi
  unset legacy_count

  legacy_password=$(sed -n 's/^DEMO_OPERATOR_PASSWORD=//p' "$ENV_FILE")
  if [ -z "$legacy_password" ]; then
    echo "A credencial legada do operador demo está vazia." >&2
    unset legacy_password
    exit 1
  fi

  if [ -f "$OPERATOR_PASSWORD_FILE" ]; then
    current_password=$(tr -d '\r\n' < "$OPERATOR_PASSWORD_FILE")
    if [ -z "$current_password" ]; then
      echo "A credencial privada do operador demo está vazia." >&2
      unset legacy_password current_password
      exit 1
    fi
    if [ "$current_password" != "$legacy_password" ]; then
      echo "Conflito entre a credencial demo legada e o secret file; nenhuma fonte foi alterada." >&2
      unset legacy_password current_password
      exit 1
    fi
    unset current_password
  else
    printf '%s\n' "$legacy_password" > "$OPERATOR_PASSWORD_FILE"
    chmod 600 "$OPERATOR_PASSWORD_FILE"
  fi
  unset legacy_password

  filtered_env="$STATE_DIR/.env.migrating"
  grep -v '^DEMO_OPERATOR_PASSWORD=' "$ENV_FILE" > "$filtered_env"
  chmod 600 "$filtered_env"
  mv "$filtered_env" "$ENV_FILE"
}

ensure_configuration() {
  umask 077
  mkdir -p "$SECRETS_DIR"
  chmod 700 "$STATE_DIR" "$SECRETS_DIR"

  if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" <<ENV
POSTGRES_DB=meufinanceiro_demo
POSTGRES_USER=meufinanceiro_demo_admin
POSTGRES_PASSWORD=$(generate_password)
APP_DATABASE_USER=meufinanceiro_demo_app
APP_DATABASE_PASSWORD=$(generate_password)
APP_HTTP_PORT=8081
APP_DEMO_MODE=true
APP_KEYRING_FILE_HOST=.demo/secrets/keyring.json
DEMO_OPERATOR_PASSWORD_FILE_HOST=.demo/secrets/operator_password.txt
ENV
  fi
  chmod 600 "$ENV_FILE"

  grep -q '^APP_DEMO_MODE=true$' "$ENV_FILE" || {
    echo "A configuração demo existente não possui APP_DEMO_MODE=true." >&2
    exit 1
  }
  grep -q '^POSTGRES_DB=meufinanceiro_demo$' "$ENV_FILE" || {
    echo "A configuração demo existente usa um banco inesperado." >&2
    exit 1
  }

  migrate_legacy_operator_password

  if ! grep -q '^DEMO_OPERATOR_PASSWORD_FILE_HOST=' "$ENV_FILE"; then
    printf '%s\n' \
      'DEMO_OPERATOR_PASSWORD_FILE_HOST=.demo/secrets/operator_password.txt' \
      >> "$ENV_FILE"
  fi

  if [ ! -f "$OPERATOR_PASSWORD_FILE" ]; then
    generate_password > "$OPERATOR_PASSWORD_FILE"
  fi
  chmod 600 "$OPERATOR_PASSWORD_FILE"

  if [ ! -s "$OPERATOR_PASSWORD_FILE" ]; then
    echo "A credencial privada do operador demo está vazia." >&2
    exit 1
  fi

  if [ ! -f "$KEYRING_FILE" ]; then
    python3 "$ROOT_DIR/infra/scripts/manage-secrets.py" init --path "$KEYRING_FILE"
  else
    python3 "$ROOT_DIR/infra/scripts/manage-secrets.py" validate --path "$KEYRING_FILE" >/dev/null
  fi
}

compose_base() {
  docker compose \
    --project-name "$PROJECT_NAME" \
    --env-file "$ENV_FILE" \
    "$@"
}

compose_demo() {
  docker compose \
    --project-name "$PROJECT_NAME" \
    --env-file "$ENV_FILE" \
    --profile demo \
    "$@"
}

run_fixture_command() {
  compose_demo run --rm --no-deps demo-fixture \
    python -m meufinanceiro_persistence.demo_cli "$1"
}

ensure_configuration
cd "$ROOT_DIR"

case "$ACTION" in
  up)
    compose_base up --build --detach --wait --wait-timeout 180
    run_fixture_command load
    PORT=$(awk -F= '$1 == "APP_HTTP_PORT" {print $2}' "$ENV_FILE" | tail -n 1)
    python3 - "$PORT" <<'PY'
import json
import sys
import time
import urllib.request

port = sys.argv[1]
url = f"http://127.0.0.1:{port}/api/v1/demo/status"
for _ in range(60):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            payload = json.load(response)
        if payload.get("enabled") is True and payload.get("loaded") is True:
            print(json.dumps(payload, sort_keys=True))
            break
    except Exception:
        pass
    time.sleep(1)
else:
    raise SystemExit("O ambiente demo não confirmou fixture carregada.")
PY
    echo "MeuFinanceiro demo disponível em http://127.0.0.1:${PORT}"
    echo "Login demo: demo"
    printf 'Senha demo: '
    cat "$OPERATOR_PASSWORD_FILE"
    ;;
  load|status|reset)
    run_fixture_command "$ACTION"
    ;;
  down)
    compose_demo down --remove-orphans --timeout 40
    ;;
  purge)
    compose_demo down --volumes --remove-orphans --timeout 40
    rm -rf "$STATE_DIR"
    ;;
esac
