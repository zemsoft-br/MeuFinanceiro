#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
KEYRING_FILE="$ROOT_DIR/.secrets/keyring.json"
BACKUP_ROOT="$ROOT_DIR/.backups"
ACKNOWLEDGED=false

usage() {
  cat >&2 <<'EOF'
Uso: bash infra/scripts/backup-create.sh --acknowledge-sensitive [--output-dir DIRETORIO]

O bundle contém o dump do banco, senhas da instalação e a chave mestra.
Armazene-o somente em destino criptografado e nunca o anexe a issues ou artifacts.
EOF
}

sha256_file() {
  python3 - "$1" <<'PY'
import hashlib
import sys

path = sys.argv[1]
digest = hashlib.sha256()
with open(path, "rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
print(digest.hexdigest())
PY
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --acknowledge-sensitive)
      ACKNOWLEDGED=true
      shift
      ;;
    --output-dir)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      BACKUP_ROOT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

if [[ "$ACKNOWLEDGED" != true ]]; then
  echo "Confirme o tratamento do bundle sensível com --acknowledge-sensitive." >&2
  exit 2
fi

for command_name in docker python3; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "$command_name não encontrado." >&2
    exit 1
  }
done
docker compose version >/dev/null 2>&1 || {
  echo "Docker Compose v2 não encontrado." >&2
  exit 1
}

[[ -f "$ENV_FILE" ]] || {
  echo ".env não encontrado. Inicialize o ambiente comum antes do backup." >&2
  exit 1
}
[[ -f "$KEYRING_FILE" ]] || {
  echo "Keyring não encontrado. Inicialize o ambiente comum antes do backup." >&2
  exit 1
}

# Preserve a relative destination against the caller's current directory before
# the operator changes into the repository root to run Docker Compose.
BACKUP_ROOT="$(python3 - "$BACKUP_ROOT" <<'PY'
import sys
from pathlib import Path

print(Path(sys.argv[1]).expanduser().resolve())
PY
)"

if [[ ! -e "$BACKUP_ROOT" ]]; then
  mkdir -m 700 -p "$BACKUP_ROOT"
elif [[ ! -d "$BACKUP_ROOT" ]]; then
  echo "O destino de backup não é um diretório." >&2
  exit 1
fi

backup_id="meufinanceiro-$(date -u +%Y%m%dT%H%M%SZ)-$(python3 -c 'import secrets; print(secrets.token_hex(4))')"
final_dir="$BACKUP_ROOT/$backup_id"
temp_dir="$BACKUP_ROOT/.$backup_id.tmp"
container_dump="/tmp/$backup_id.dump"
postgres_container=""
published=false

cleanup() {
  if [[ -n "$postgres_container" ]]; then
    docker compose exec -T postgres rm -f "$container_dump" >/dev/null 2>&1 || true
  fi
  if [[ "$published" != true ]]; then
    rm -rf "$temp_dir"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

[[ ! -e "$final_dir" && ! -e "$temp_dir" ]] || {
  echo "Já existe um bundle com o identificador gerado." >&2
  exit 1
}

cd "$ROOT_DIR"
postgres_container="$(docker compose ps -q postgres)"
[[ -n "$postgres_container" ]] || {
  echo "Container PostgreSQL do ambiente comum não está em execução." >&2
  exit 1
}
health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$postgres_container")"
[[ "$health" == "healthy" ]] || {
  echo "PostgreSQL não está saudável; backup recusado." >&2
  exit 1
}

env_hash_before="$(sha256_file "$ENV_FILE")"
keyring_hash_before="$(sha256_file "$KEYRING_FILE")"

mkdir "$temp_dir"
chmod 700 "$temp_dir" 2>/dev/null || true
cp "$ENV_FILE" "$temp_dir/installation.env"
cp "$KEYRING_FILE" "$temp_dir/keyring.json"
chmod 600 "$temp_dir/installation.env" "$temp_dir/keyring.json" 2>/dev/null || true

# O dump é criado dentro do container e copiado com docker cp. Isso evita
# redirecionamento binário pelo host e preserva o formato custom no PowerShell.
docker compose exec -T postgres sh -ceu '
  umask 077
  pg_dump \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --format=custom \
    --no-owner \
    --no-privileges \
    --file "$1"
' -- "$container_dump"
docker cp "$postgres_container:$container_dump" "$temp_dir/database.dump" >/dev/null
docker compose exec -T postgres rm -f "$container_dump" >/dev/null
chmod 600 "$temp_dir/database.dump" 2>/dev/null || true

schema_revision="$({
  docker compose exec -T postgres sh -ceu '
    psql \
      --username "$POSTGRES_USER" \
      --dbname "$POSTGRES_DB" \
      --tuples-only \
      --no-align \
      --command "SELECT version_num FROM alembic_version;"
  '
} | tr -d '[:space:]')"
[[ -n "$schema_revision" ]] || {
  echo "Revisão Alembic não encontrada; backup recusado." >&2
  exit 1
}

if [[ "$(sha256_file "$ENV_FILE")" != "$env_hash_before" ]]; then
  echo ".env mudou durante o backup; bundle descartado." >&2
  exit 1
fi
if [[ "$(sha256_file "$KEYRING_FILE")" != "$keyring_hash_before" ]]; then
  echo "Keyring mudou durante o backup; bundle descartado." >&2
  exit 1
fi
if [[ "$(sha256_file "$temp_dir/installation.env")" != "$env_hash_before" ]]; then
  echo "Cópia de .env inconsistente; bundle descartado." >&2
  exit 1
fi
if [[ "$(sha256_file "$temp_dir/keyring.json")" != "$keyring_hash_before" ]]; then
  echo "Cópia do keyring inconsistente; bundle descartado." >&2
  exit 1
fi

database_name="$(awk -F= '$1 == "POSTGRES_DB" {print substr($0, index($0, "=") + 1)}' "$ENV_FILE" | tail -n 1)"
database_name="${database_name:-meufinanceiro}"

python3 "$SCRIPT_DIR/backup-contract.py" create \
  --bundle-dir "$temp_dir" \
  --backup-id "$backup_id" \
  --database-name "$database_name" \
  --schema-revision "$schema_revision"
python3 "$SCRIPT_DIR/backup-contract.py" validate --bundle-dir "$temp_dir" >/dev/null
chmod 600 "$temp_dir/manifest.json" 2>/dev/null || true

mv "$temp_dir" "$final_dir"
published=true
trap - EXIT INT TERM

echo "ATENÇÃO: o bundle contém senhas e chave mestra; mova-o para armazenamento criptografado." >&2
printf '%s\n' "$final_dir"
