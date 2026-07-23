#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

usage() {
  echo "Uso: bash infra/scripts/backup-verify.sh DIRETORIO_DO_BUNDLE" >&2
}

[[ $# -eq 1 ]] || { usage; exit 2; }
BUNDLE_DIR="$(CDPATH= cd -- "$1" 2>/dev/null && pwd)" || {
  echo "Diretório do bundle não encontrado." >&2
  exit 1
}

for command_name in docker python3; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "$command_name não encontrado." >&2
    exit 1
  }
done

safe_metadata="$(python3 "$SCRIPT_DIR/backup-contract.py" validate --bundle-dir "$BUNDLE_DIR")"
backup_id="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["backup_id"])' <<<"$safe_metadata")"
schema_revision="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["schema_revision"])' <<<"$safe_metadata")"
postgres_image="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["postgres_image"])' <<<"$safe_metadata")"

suffix="$(python3 -c 'import secrets; print(secrets.token_hex(4))')"
container_name="meufinanceiro-backup-verify-$suffix"
restore_user="restore_verify"
restore_database="restore_verify"
restore_password="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"

cleanup() {
  status=$?
  docker rm --force "$container_name" >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT INT TERM

docker run \
  --detach \
  --name "$container_name" \
  --network none \
  --tmpfs /var/lib/postgresql:rw,noexec,nosuid,size=512m \
  --env "POSTGRES_DB=$restore_database" \
  --env "POSTGRES_USER=$restore_user" \
  --env "POSTGRES_PASSWORD=$restore_password" \
  "$postgres_image" >/dev/null

for _ in $(seq 1 60); do
  if docker exec "$container_name" pg_isready \
    --username "$restore_user" \
    --dbname "$restore_database" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$container_name" pg_isready \
  --username "$restore_user" \
  --dbname "$restore_database" >/dev/null

port_bindings="$(docker inspect --format '{{json .HostConfig.PortBindings}}' "$container_name")"
[[ "$port_bindings" == "null" || "$port_bindings" == "{}" ]] || {
  echo "O container de verificação publicou portas inesperadamente." >&2
  exit 1
}

docker cp "$BUNDLE_DIR/database.dump" "$container_name:/tmp/database.dump" >/dev/null
docker exec "$container_name" pg_restore \
  --username "$restore_user" \
  --dbname "$restore_database" \
  --no-owner \
  --no-privileges \
  --exit-on-error \
  /tmp/database.dump

restored_revision="$(
  docker exec "$container_name" psql \
    --username "$restore_user" \
    --dbname "$restore_database" \
    --tuples-only \
    --no-align \
    --command 'SELECT version_num FROM alembic_version;' | tr -d '[:space:]'
)"
[[ "$restored_revision" == "$schema_revision" ]] || {
  echo "A revisão Alembic restaurada não corresponde ao manifesto." >&2
  exit 1
}

infra_exists="$(
  docker exec "$container_name" psql \
    --username "$restore_user" \
    --dbname "$restore_database" \
    --tuples-only \
    --no-align \
    --command "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'infra');" | tr -d '[:space:]'
)"
[[ "$infra_exists" == "t" ]] || {
  echo "O schema infra não foi restaurado." >&2
  exit 1
}

docker rm --force "$container_name" >/dev/null
trap - EXIT INT TERM
printf 'Backup %s restaurado e verificado em ambiente descartável.\n' "$backup_id"
