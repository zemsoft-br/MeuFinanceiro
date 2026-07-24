#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat >&2 <<'USAGE'
Uso: update-foundation.sh --target-ref <ref> --acknowledge-sensitive [opções]

Opções:
  --target-ref <ref>       Ref/commit Git de destino.
  --backup-dir <dir>       Diretório do bundle sensível (padrão: .backups).
  --root-dir <dir>         Checkout da instalação (padrão: raiz do script).
  --acknowledge-sensitive  Confirma que o backup contém senhas e keyring.
  --no-fetch               Não executa git fetch antes de resolver o target.
  --allow-detached         Permite checkout detached (somente validação descartável).
  --skip-checkout-advance  Não avança o checkout após sucesso (somente CI).
USAGE
}

TARGET_REF=""
BACKUP_DIR=""
ROOT_OVERRIDE=""
ACKNOWLEDGE_SENSITIVE=0
NO_FETCH=0
ALLOW_DETACHED=0
SKIP_CHECKOUT_ADVANCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target-ref) TARGET_REF=${2:?target ausente}; shift 2 ;;
    --backup-dir) BACKUP_DIR=${2:?diretório ausente}; shift 2 ;;
    --root-dir) ROOT_OVERRIDE=${2:?raiz ausente}; shift 2 ;;
    --acknowledge-sensitive) ACKNOWLEDGE_SENSITIVE=1; shift ;;
    --no-fetch) NO_FETCH=1; shift ;;
    --allow-detached) ALLOW_DETACHED=1; shift ;;
    --skip-checkout-advance) SKIP_CHECKOUT_ADVANCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Argumento desconhecido: $1" >&2; usage; exit 64 ;;
  esac
done

[[ -n "$TARGET_REF" ]] || { echo "--target-ref é obrigatório." >&2; exit 64; }
[[ "$ACKNOWLEDGE_SENSITIVE" -eq 1 ]] || {
  echo "Use --acknowledge-sensitive para confirmar o conteúdo sensível do backup." >&2
  exit 64
}

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEFAULT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
ROOT_DIR=$(CDPATH= cd -- "${ROOT_OVERRIDE:-$DEFAULT_ROOT}" && pwd)
ENV_FILE="$ROOT_DIR/.env"
KEYRING_FILE="$ROOT_DIR/.secrets/keyring.json"
UPDATES_DIR="$ROOT_DIR/.updates"
BACKUP_DIR=${BACKUP_DIR:-"$ROOT_DIR/.backups"}
UPDATE_ID="update-$(date -u +%Y%m%dT%H%M%SZ)-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
STATE_DIR="$UPDATES_DIR/$UPDATE_ID"
STATE_FILE="$STATE_DIR/state.json"
LOCK_DIR="$UPDATES_DIR/update.lock"
TARGET_WORKTREE="${TMPDIR:-/tmp}/meufinanceiro-$UPDATE_ID"
SOURCE_COMMIT=""
TARGET_COMMIT=""
SOURCE_SCHEMA=""
CURRENT_SCHEMA=""
BACKUP_ID=""
VOLUME_FINGERPRINT=""
ENV_HASH=""
KEYRING_HASH=""
LOCK_HELD=0
WORKTREE_ADDED=0

mkdir -p "$UPDATES_DIR" "$STATE_DIR"

write_state() {
  local status=$1
  local detail=${2:-}
  STATUS="$status" DETAIL="$detail" UPDATE_ID="$UPDATE_ID" \
  SOURCE_COMMIT="$SOURCE_COMMIT" TARGET_COMMIT="$TARGET_COMMIT" \
  SOURCE_SCHEMA="$SOURCE_SCHEMA" CURRENT_SCHEMA="$CURRENT_SCHEMA" \
  BACKUP_ID="$BACKUP_ID" VOLUME_FINGERPRINT="$VOLUME_FINGERPRINT" \
  STATE_FILE="$STATE_FILE" python3 - <<'PY'
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

state_file = Path(os.environ["STATE_FILE"])
payload = {
    "format": "meufinanceiro-foundation-update",
    "version": 1,
    "update_id": os.environ["UPDATE_ID"],
    "status": os.environ["STATUS"],
    "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "source_commit": os.environ.get("SOURCE_COMMIT") or None,
    "target_commit": os.environ.get("TARGET_COMMIT") or None,
    "source_schema_revision": os.environ.get("SOURCE_SCHEMA") or None,
    "current_schema_revision": os.environ.get("CURRENT_SCHEMA") or None,
    "backup_id": os.environ.get("BACKUP_ID") or None,
    "volume_fingerprint_sha256": os.environ.get("VOLUME_FINGERPRINT") or None,
    "detail": os.environ.get("DETAIL") or None,
}
state_file.parent.mkdir(parents=True, exist_ok=True)
fd, temporary = tempfile.mkstemp(prefix=".state-", suffix=".json", dir=state_file.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2)
        handle.write("\n")
    os.replace(temporary, state_file)
finally:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
PY
}

cleanup() {
  local exit_code=$?
  if [[ "$WORKTREE_ADDED" -eq 1 ]]; then
    git -C "$ROOT_DIR" worktree remove --force "$TARGET_WORKTREE" >/dev/null 2>&1 || true
  fi
  rm -rf "$TARGET_WORKTREE" >/dev/null 2>&1 || true
  if [[ "$LOCK_HELD" -eq 1 ]]; then
    rmdir "$LOCK_DIR" >/dev/null 2>&1 || true
  fi
  exit "$exit_code"
}
trap cleanup EXIT

for command_name in git docker python3 sha256sum; do
  command -v "$command_name" >/dev/null 2>&1 || {
    write_state FAILED_PRECHECK "missing_${command_name}"
    echo "$command_name não encontrado." >&2
    exit 1
  }
done
docker compose version >/dev/null 2>&1 || {
  write_state FAILED_PRECHECK "compose_v2_missing"
  echo "Docker Compose v2 não encontrado." >&2
  exit 1
}

mkdir "$LOCK_DIR" 2>/dev/null || {
  write_state FAILED_PRECHECK "update_lock_busy"
  echo "Outra atualização está em andamento nesta instalação." >&2
  exit 1
}
LOCK_HELD=1

[[ -f "$ENV_FILE" ]] || { write_state FAILED_PRECHECK "env_missing"; echo ".env não encontrado." >&2; exit 1; }
[[ -f "$KEYRING_FILE" ]] || { write_state FAILED_PRECHECK "keyring_missing"; echo "Keyring não encontrado." >&2; exit 1; }
[[ -f "$ROOT_DIR/compose.yaml" ]] || { write_state FAILED_PRECHECK "compose_missing"; echo "compose.yaml não encontrado." >&2; exit 1; }

git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
  write_state FAILED_PRECHECK "not_git_checkout"
  echo "A raiz informada não é um checkout Git." >&2
  exit 1
}
if ! git -C "$ROOT_DIR" diff --quiet || ! git -C "$ROOT_DIR" diff --cached --quiet; then
  write_state FAILED_PRECHECK "tracked_changes"
  echo "O checkout possui alterações rastreadas. Atualização recusada." >&2
  exit 1
fi

CURRENT_BRANCH=$(git -C "$ROOT_DIR" symbolic-ref --quiet --short HEAD || true)
if [[ "$ALLOW_DETACHED" -ne 1 && "$CURRENT_BRANCH" != "develop" ]]; then
  write_state FAILED_PRECHECK "branch_not_develop"
  echo "A atualização comum deve ser executada na branch develop." >&2
  exit 1
fi

SOURCE_COMMIT=$(git -C "$ROOT_DIR" rev-parse HEAD)
if [[ "$NO_FETCH" -ne 1 ]]; then
  if ! git -C "$ROOT_DIR" fetch --prune origin develop >/dev/null; then
    write_state FAILED_PRECHECK "git_fetch_failed"
    echo "Não foi possível atualizar a referência origin/develop." >&2
    exit 1
  fi
fi
if ! TARGET_COMMIT=$(git -C "$ROOT_DIR" rev-parse "$TARGET_REF^{commit}" 2>/dev/null); then
  write_state FAILED_PRECHECK "target_unresolved"
  echo "A referência Git de destino não pôde ser resolvida." >&2
  exit 1
fi
git -C "$ROOT_DIR" merge-base --is-ancestor "$SOURCE_COMMIT" "$TARGET_COMMIT" || {
  write_state FAILED_PRECHECK "target_not_fast_forward"
  echo "O target não é descendente fast-forward do commit atual." >&2
  exit 1
}

ENV_HASH=$(sha256sum "$ENV_FILE" | awk '{print $1}')
KEYRING_HASH=$(sha256sum "$KEYRING_FILE" | awk '{print $1}')
volume_description=$(docker volume inspect meufinanceiro_postgres_data \
  --format '{{.Name}}|{{.Mountpoint}}|{{.CreatedAt}}' 2>/dev/null) || {
  write_state FAILED_PRECHECK "volume_missing"
  echo "Volume PostgreSQL da instalação não encontrado." >&2
  exit 1
}
VOLUME_FINGERPRINT=$(printf '%s' "$volume_description" | sha256sum | awk '{print $1}')

get_env_value() {
  local key=$1
  awk -F= -v wanted="$key" '$1 == wanted {sub(/^[^=]*=/, ""); value=$0} END {print value}' "$ENV_FILE"
}
POSTGRES_USER_VALUE=$(get_env_value POSTGRES_USER)
POSTGRES_DB_VALUE=$(get_env_value POSTGRES_DB)
[[ -n "$POSTGRES_USER_VALUE" && -n "$POSTGRES_DB_VALUE" ]] || {
  write_state FAILED_PRECHECK "database_contract_missing"
  echo "POSTGRES_USER ou POSTGRES_DB ausente no .env." >&2
  exit 1
}

compose_for() {
  local project_dir=$1
  shift
  APP_KEYRING_FILE_HOST="$KEYRING_FILE" docker compose \
    --project-directory "$project_dir" \
    --env-file "$ENV_FILE" \
    -f "$project_dir/compose.yaml" "$@"
}

get_schema_revision() {
  local project_dir=$1
  compose_for "$project_dir" exec -T postgres psql \
    --username "$POSTGRES_USER_VALUE" \
    --dbname "$POSTGRES_DB_VALUE" \
    --tuples-only --no-align \
    --command 'SELECT version_num FROM alembic_version;' 2>/dev/null \
    | awk 'NF {gsub(/^[[:space:]]+|[[:space:]]+$/, ""); print}' \
    | tail -n 1
}

SOURCE_SCHEMA=$(get_schema_revision "$ROOT_DIR")
[[ -n "$SOURCE_SCHEMA" ]] || {
  write_state FAILED_PRECHECK "schema_revision_missing"
  echo "Revisão Alembic atual não encontrada." >&2
  exit 1
}
CURRENT_SCHEMA="$SOURCE_SCHEMA"

if [[ "$SOURCE_COMMIT" == "$TARGET_COMMIT" ]]; then
  write_state APPLIED "target_already_applied"
  printf '%s\n' "$STATE_FILE"
  exit 0
fi

if ! bundle_path=$(bash "$ROOT_DIR/infra/scripts/backup-create.sh" \
  --acknowledge-sensitive --output-dir "$BACKUP_DIR"); then
  write_state FAILED_PRECHECK "backup_create_failed"
  echo "A criação do backup pré-atualização falhou." >&2
  exit 1
fi
if ! bash "$ROOT_DIR/infra/scripts/backup-verify.sh" "$bundle_path"; then
  write_state FAILED_PRECHECK "backup_verify_failed"
  echo "A restauração descartável do backup pré-atualização falhou." >&2
  exit 1
fi
BACKUP_ID=$(basename "$bundle_path")
write_state PREPARED "backup_verified"

git -C "$ROOT_DIR" worktree add --detach "$TARGET_WORKTREE" "$TARGET_COMMIT" >/dev/null
WORKTREE_ADDED=1

if ! compose_for "$TARGET_WORKTREE" build; then
  write_state FAILED_PRECHECK "target_build_failed"
  echo "Build do target falhou; a instalação original não foi alterada." >&2
  exit 1
fi

rollback_after_failure() {
  CURRENT_SCHEMA=$(get_schema_revision "$TARGET_WORKTREE" || true)
  if [[ -n "${MEUFINANCEIRO_UPDATE_TEST_SCHEMA_OVERRIDE_AFTER_FAILURE:-}" ]]; then
    CURRENT_SCHEMA="$MEUFINANCEIRO_UPDATE_TEST_SCHEMA_OVERRIDE_AFTER_FAILURE"
  fi
  if [[ -n "$CURRENT_SCHEMA" && "$CURRENT_SCHEMA" == "$SOURCE_SCHEMA" ]]; then
    if compose_for "$ROOT_DIR" up --build --detach --wait --wait-timeout 180 && \
       APP_HTTP_PORT="$(get_env_value APP_HTTP_PORT)" \
         bash "$ROOT_DIR/tests/smoke/compose-smoke.sh"; then
      local rollback_volume_description=""
      rollback_volume_description=$(docker volume inspect meufinanceiro_postgres_data \
        --format '{{.Name}}|{{.Mountpoint}}|{{.CreatedAt}}' 2>/dev/null || true)
      if [[ "$(sha256sum "$ENV_FILE" | awk '{print $1}')" == "$ENV_HASH" && \
            "$(sha256sum "$KEYRING_FILE" | awk '{print $1}')" == "$KEYRING_HASH" && \
            -n "$rollback_volume_description" && \
            "$(printf '%s' "$rollback_volume_description" | sha256sum | awk '{print $1}')" == "$VOLUME_FINGERPRINT" ]]; then
        write_state ROLLED_BACK "target_failed_schema_unchanged"
        echo "A atualização falhou e o commit anterior foi restaurado com schema inalterado." >&2
        return 2
      fi
    fi
  fi

  compose_for "$TARGET_WORKTREE" stop caddy api worker web >/dev/null 2>&1 || true
  write_state ROLLBACK_REQUIRES_COORDINATED_RESTORE "schema_changed_or_unknown"
  echo "A atualização falhou após possível avanço de schema." >&2
  echo "Rollback automático bloqueado. Preserve o bundle $BACKUP_ID." >&2
  return 3
}

run_controlled_rollback() {
  set +e
  rollback_after_failure
  local rollback_code=$?
  set -e
  exit "$rollback_code"
}

if ! compose_for "$TARGET_WORKTREE" up --detach --wait --wait-timeout 180; then
  run_controlled_rollback
fi

if [[ "${MEUFINANCEIRO_UPDATE_TEST_FAIL_AFTER_START:-0}" == "1" ]]; then
  run_controlled_rollback
fi

if ! APP_HTTP_PORT="$(get_env_value APP_HTTP_PORT)" \
  bash "$TARGET_WORKTREE/tests/smoke/compose-smoke.sh"; then
  run_controlled_rollback
fi

if ! CURRENT_SCHEMA=$(get_schema_revision "$TARGET_WORKTREE") || [[ -z "$CURRENT_SCHEMA" ]]; then
  run_controlled_rollback
fi
if [[ "$(sha256sum "$ENV_FILE" | awk '{print $1}')" != "$ENV_HASH" ]]; then
  run_controlled_rollback
fi
if [[ "$(sha256sum "$KEYRING_FILE" | awk '{print $1}')" != "$KEYRING_HASH" ]]; then
  run_controlled_rollback
fi
if ! current_volume_description=$(docker volume inspect meufinanceiro_postgres_data \
  --format '{{.Name}}|{{.Mountpoint}}|{{.CreatedAt}}' 2>/dev/null); then
  run_controlled_rollback
fi
if [[ "$(printf '%s' "$current_volume_description" | sha256sum | awk '{print $1}')" != "$VOLUME_FINGERPRINT" ]]; then
  run_controlled_rollback
fi

if [[ "$SKIP_CHECKOUT_ADVANCE" -ne 1 ]]; then
  if ! git -C "$ROOT_DIR" merge --ff-only "$TARGET_COMMIT"; then
    run_controlled_rollback
  fi
fi
write_state APPLIED "target_started_and_smoke_passed"
printf '%s\n' "$STATE_FILE"
