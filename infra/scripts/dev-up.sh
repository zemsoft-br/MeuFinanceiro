#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
ENV_FILE="$ROOT_DIR/.env"
KEYRING_FILE="$ROOT_DIR/.secrets/keyring.json"

command -v docker >/dev/null 2>&1 || {
  echo "Docker não encontrado." >&2
  exit 1
}

command -v python3 >/dev/null 2>&1 || {
  echo "Python 3 é necessário para gerar e validar a configuração segura local." >&2
  exit 1
}

docker compose version >/dev/null 2>&1 || {
  echo "Docker Compose v2 não encontrado." >&2
  exit 1
}

generate_password() {
  python3 -c 'import secrets; print(secrets.token_hex(24))'
}

if [ ! -f "$ENV_FILE" ]; then
  ADMIN_PASSWORD=$(generate_password)
  APP_PASSWORD=$(generate_password)
  cat > "$ENV_FILE" <<ENV
POSTGRES_DB=meufinanceiro
POSTGRES_USER=meufinanceiro_admin
POSTGRES_PASSWORD=$ADMIN_PASSWORD
APP_DATABASE_USER=meufinanceiro_app
APP_DATABASE_PASSWORD=$APP_PASSWORD
APP_HTTP_PORT=8080
WEB_RUNTIME_TARGET=flutter-runtime
APP_KEYRING_FILE_HOST=.secrets/keyring.json
ENV
  echo "Configuração local criada em .env."
else
  if ! grep -q '^APP_DATABASE_USER=' "$ENV_FILE"; then
    printf '\nAPP_DATABASE_USER=meufinanceiro_app\n' >> "$ENV_FILE"
  fi
  if ! grep -q '^APP_DATABASE_PASSWORD=' "$ENV_FILE"; then
    printf 'APP_DATABASE_PASSWORD=%s\n' "$(generate_password)" >> "$ENV_FILE"
  fi
  if ! grep -q '^WEB_RUNTIME_TARGET=' "$ENV_FILE"; then
    printf 'WEB_RUNTIME_TARGET=flutter-runtime\n' >> "$ENV_FILE"
  fi
  if ! grep -q '^APP_KEYRING_FILE_HOST=' "$ENV_FILE"; then
    printf 'APP_KEYRING_FILE_HOST=.secrets/keyring.json\n' >> "$ENV_FILE"
  fi
fi
chmod 600 "$ENV_FILE"

WEB_RUNTIME_TARGET=$(awk -F= '$1 == "WEB_RUNTIME_TARGET" {print $2}' "$ENV_FILE" | tail -n 1)
WEB_RUNTIME_TARGET="${WEB_RUNTIME_TARGET:-flutter-runtime}"
case "$WEB_RUNTIME_TARGET" in
  flutter-runtime | react-runtime) ;;
  *)
    printf 'WEB_RUNTIME_TARGET deve ser flutter-runtime ou react-runtime.\n' >&2
    exit 1
    ;;
esac

if [ ! -f "$KEYRING_FILE" ]; then
  python3 "$ROOT_DIR/infra/scripts/manage-secrets.py" init --path "$KEYRING_FILE"
else
  python3 "$ROOT_DIR/infra/scripts/manage-secrets.py" validate --path "$KEYRING_FILE" >/dev/null
fi

cd "$ROOT_DIR"
docker compose up --build --detach --wait

APP_HTTP_PORT=$(awk -F= '$1 == "APP_HTTP_PORT" {print $2}' "$ENV_FILE" | tail -n 1)
APP_HTTP_PORT="${APP_HTTP_PORT:-8080}" \
  WEB_RUNTIME_TARGET="$WEB_RUNTIME_TARGET" \
  "$ROOT_DIR/tests/smoke/compose-smoke.sh"
echo "MeuFinanceiro ($WEB_RUNTIME_TARGET) disponível em http://127.0.0.1:${APP_HTTP_PORT:-8080}"
