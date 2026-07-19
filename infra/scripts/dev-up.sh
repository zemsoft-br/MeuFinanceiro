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

if [ ! -f "$ENV_FILE" ]; then
  PASSWORD=$(python3 -c 'import secrets; print(secrets.token_hex(24))')
  cat > "$ENV_FILE" <<ENV
POSTGRES_DB=meufinanceiro
POSTGRES_USER=meufinanceiro
POSTGRES_PASSWORD=$PASSWORD
APP_HTTP_PORT=8080
APP_KEYRING_FILE_HOST=.secrets/keyring.json
ENV
  chmod 600 "$ENV_FILE"
  echo "Configuração local criada em .env."
elif ! grep -q '^APP_KEYRING_FILE_HOST=' "$ENV_FILE"; then
  printf '\nAPP_KEYRING_FILE_HOST=.secrets/keyring.json\n' >> "$ENV_FILE"
fi

if [ ! -f "$KEYRING_FILE" ]; then
  python3 "$ROOT_DIR/infra/scripts/manage-secrets.py" init --path "$KEYRING_FILE"
else
  python3 "$ROOT_DIR/infra/scripts/manage-secrets.py" validate --path "$KEYRING_FILE" >/dev/null
fi

cd "$ROOT_DIR"
docker compose up --build --detach
"$ROOT_DIR/tests/smoke/compose-smoke.sh"

echo "MeuFinanceiro disponível em http://127.0.0.1:${APP_HTTP_PORT:-8080}"
