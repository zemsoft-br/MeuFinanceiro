#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat >&2 <<'USAGE'
Uso: diagnostics-export.sh [opções]

Opções:
  --output-dir <dir>  Diretório do arquivo final (padrão: .diagnostics).
  --root-dir <dir>    Checkout da instalação (padrão: raiz do script).
  --base-url <url>    Endpoint HTTP local (padrão: http://127.0.0.1:8080).
  -h, --help          Exibe esta ajuda.

O bundle é somente leitura e nunca inclui .env, keyring, dumps ou credenciais.
Revise o arquivo extraído antes de compartilhá-lo.
USAGE
}

OUTPUT_DIR=""
ROOT_OVERRIDE=""
BASE_URL="http://127.0.0.1:8080"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir) OUTPUT_DIR=${2:?diretório ausente}; shift 2 ;;
    --root-dir) ROOT_OVERRIDE=${2:?raiz ausente}; shift 2 ;;
    --base-url) BASE_URL=${2:?URL ausente}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Argumento desconhecido: $1" >&2; usage; exit 64 ;;
  esac
done

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEFAULT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
ROOT_DIR=$(CDPATH= cd -- "${ROOT_OVERRIDE:-$DEFAULT_ROOT}" && pwd)
OUTPUT_DIR=${OUTPUT_DIR:-"$ROOT_DIR/.diagnostics"}
ENV_FILE="$ROOT_DIR/.env"
KEYRING_FILE="$ROOT_DIR/.secrets/keyring.json"
COMPOSE_FILE="$ROOT_DIR/compose.yaml"
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
RANDOM_SUFFIX=$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')
BUNDLE_ID="meufinanceiro-diagnostics-$TIMESTAMP-$RANDOM_SUFFIX"
TEMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/$BUNDLE_ID.XXXXXX")
STAGING_DIR="$TEMP_ROOT/$BUNDLE_ID"
ARCHIVE_PATH="$OUTPUT_DIR/$BUNDLE_ID.tar.gz"
DOCTOR_EXIT=0

cleanup() {
  rm -rf "$TEMP_ROOT" >/dev/null 2>&1 || true
}
trap cleanup EXIT

for command_name in git python3 tar; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "$command_name não encontrado; não é possível gerar o bundle." >&2
    exit 1
  }
done

mkdir -p "$STAGING_DIR" "$OUTPUT_DIR"
umask 077

SANITIZER="$TEMP_ROOT/sanitize.py"
cat > "$SANITIZER" <<'PY'
import re
import sys
from pathlib import Path

root = sys.argv[1]
home = sys.argv[2]
text = sys.stdin.read()
for value, replacement in ((root, "<REPOSITORY>"), (home, "<HOME>")):
    if value:
        text = text.replace(value, replacement)
        text = text.replace(value.replace("\\", "/"), replacement)

patterns = (
    (r"(?i)(authorization\s*[:=]\s*bearer\s+)[A-Za-z0-9._~+/-]+=*", r"\1[REDACTED]"),
    (r"(?i)(postgres(?:ql)?://)([^@\s/]+)(@)", r"\1[REDACTED]\3"),
    (
        r"(?i)\b(POSTGRES_PASSWORD|APP_DATABASE_PASSWORD|DATABASE_URL|ACCESS_TOKEN|REFRESH_TOKEN|API_KEY|CLIENT_SECRET|PRIVATE_KEY)\b\s*[:=]\s*([^\s,;]+)",
        r"\1=[REDACTED]",
    ),
    (r'(?i)"(password|database_url|access_token|refresh_token|client_secret|private_key)"\s*:\s*"[^"]*"', r'"\1":"[REDACTED]"'),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", "[REDACTED_PRIVATE_KEY]"),
    (r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b", "[REDACTED_JWT]"),
)
for pattern, replacement in patterns:
    text = re.sub(pattern, replacement, text, flags=re.DOTALL if "PRIVATE KEY" in pattern else 0)

sys.stdout.write(text)
PY

sanitize_to() {
  local destination=$1
  python3 "$SANITIZER" "$ROOT_DIR" "${HOME:-}" > "$destination"
}

write_command() {
  local destination=$1
  shift
  {
    printf '$'
    printf ' %q' "$@"
    printf '\n'
    "$@" 2>&1 || true
  } | sanitize_to "$destination"
}

compose_available=0
if command -v docker >/dev/null 2>&1 && \
   docker version >/dev/null 2>&1 && \
   docker compose version >/dev/null 2>&1 && \
   [[ -f "$COMPOSE_FILE" && -f "$ENV_FILE" ]]; then
  compose_available=1
fi

compose() {
  APP_KEYRING_FILE_HOST="$KEYRING_FILE" docker compose \
    --project-directory "$ROOT_DIR" \
    --env-file "$ENV_FILE" \
    -f "$COMPOSE_FILE" "$@"
}

cat > "$STAGING_DIR/README.txt" <<'EOF'
Bundle diagnóstico sanitizado do MeuFinanceiro.

Revise todos os arquivos antes de compartilhar. Este bundle não deve conter
.env, keyring, dumps, senhas, tokens, URLs de banco com credenciais ou chaves
privadas. Ele não substitui backup e não autoriza procedimentos destrutivos.
EOF

{
  echo "git=$(git --version 2>/dev/null || echo unavailable)"
  if command -v docker >/dev/null 2>&1; then
    echo "docker_client=$(docker --version 2>/dev/null || echo unavailable)"
    echo "docker_compose=$(docker compose version 2>/dev/null || echo unavailable)"
    if docker version >/dev/null 2>&1; then
      docker version --format 'docker_server={{.Server.Version}}' 2>/dev/null || true
    else
      echo "docker_server=unavailable"
    fi
  else
    echo "docker_client=unavailable"
    echo "docker_compose=unavailable"
    echo "docker_server=unavailable"
  fi
  echo "python=$(python3 --version 2>&1)"
} | sanitize_to "$STAGING_DIR/versions.txt"

{
  echo "kernel=$(uname -srm 2>/dev/null || echo unavailable)"
  echo "architecture=$(uname -m 2>/dev/null || echo unavailable)"
  if [[ -r /etc/os-release ]]; then
    grep -E '^(ID|VERSION_ID)=' /etc/os-release || true
  fi
  df -h "$ROOT_DIR" 2>/dev/null | awk 'NR <= 2 {print}' || true
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    docker info --format 'docker_os={{.OperatingSystem}}\ndocker_arch={{.Architecture}}\ndocker_cpus={{.NCPU}}\ndocker_memory={{.MemTotal}}' 2>/dev/null || true
  fi
} | sanitize_to "$STAGING_DIR/host.txt"

{
  echo "commit=$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || echo unavailable)"
  echo "branch=$(git -C "$ROOT_DIR" symbolic-ref --quiet --short HEAD 2>/dev/null || echo detached)"
  echo "tracked_changes_begin"
  git -C "$ROOT_DIR" status --porcelain --untracked-files=no 2>/dev/null || true
  echo "tracked_changes_end"
} | sanitize_to "$STAGING_DIR/git.txt"

{
  if [[ -f "$ENV_FILE" ]]; then
    echo "env_present=true"
    echo "env_sha256=$(sha256sum "$ENV_FILE" | awk '{print $1}')"
  else
    echo "env_present=false"
  fi
  if [[ -f "$KEYRING_FILE" ]]; then
    echo "keyring_present=true"
    echo "keyring_sha256=$(sha256sum "$KEYRING_FILE" | awk '{print $1}')"
  else
    echo "keyring_present=false"
  fi
  echo "compose_present=$([[ -f "$COMPOSE_FILE" ]] && echo true || echo false)"
} > "$STAGING_DIR/config-presence.txt"

set +e
MEUFINANCEIRO_BASE_URL="$BASE_URL" bash "$ROOT_DIR/infra/scripts/doctor.sh" \
  > "$TEMP_ROOT/doctor.raw" 2>&1
DOCTOR_EXIT=$?
set -e
sanitize_to "$STAGING_DIR/doctor.txt" < "$TEMP_ROOT/doctor.raw"
printf '\ndoctor_exit_code=%s\n' "$DOCTOR_EXIT" >> "$STAGING_DIR/doctor.txt"

if [[ "$compose_available" -eq 1 ]]; then
  COMPOSE_SELECTOR="$TEMP_ROOT/select-compose.py"
  cat > "$COMPOSE_SELECTOR" <<'PY'
import json
import sys

raw = sys.stdin.read().strip()
items = []
if raw:
    try:
        parsed = json.loads(raw)
        items = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        for line in raw.splitlines():
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                pass
allowed = []
for item in items:
    publishers = []
    for publisher in item.get("Publishers") or []:
        publishers.append(
            {
                "protocol": publisher.get("Protocol"),
                "target_port": publisher.get("TargetPort"),
                "published_port": publisher.get("PublishedPort"),
                "url": publisher.get("URL"),
            }
        )
    allowed.append(
        {
            "service": item.get("Service"),
            "state": item.get("State"),
            "health": item.get("Health"),
            "exit_code": item.get("ExitCode"),
            "image": item.get("Image"),
            "publishers": publishers,
        }
    )
json.dump(allowed, sys.stdout, indent=2, sort_keys=True)
sys.stdout.write("\n")
PY
  compose ps --all --format json 2>/dev/null \
    | python3 "$COMPOSE_SELECTOR" \
    | sanitize_to "$STAGING_DIR/compose-ps.json"

  compose logs --no-color --tail=200 api worker migrate db-bootstrap postgres caddy web 2>&1 \
    | sanitize_to "$STAGING_DIR/logs.txt"

  {
    compose exec -T postgres sh -c \
      'psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --tuples-only --no-align --command "SELECT version_num FROM alembic_version;"' \
      2>/dev/null || echo "unavailable"
  } | awk 'NF {gsub(/^[[:space:]]+|[[:space:]]+$/, ""); print}' \
    | tail -n 1 > "$STAGING_DIR/schema-revision.txt"
else
  printf '[]\n' > "$STAGING_DIR/compose-ps.json"
  printf 'Stack indisponível; nenhum log coletado.\n' > "$STAGING_DIR/logs.txt"
  printf 'unavailable\n' > "$STAGING_DIR/schema-revision.txt"
fi

if command -v curl >/dev/null 2>&1; then
  if curl --fail --silent --show-error --max-time 5 \
    "$BASE_URL/api/v1/health/ready" > "$TEMP_ROOT/health.raw" 2>/dev/null; then
    sanitize_to "$STAGING_DIR/health.json" < "$TEMP_ROOT/health.raw"
  else
    printf '{"status":"unavailable"}\n' > "$STAGING_DIR/health.json"
  fi
else
  printf '{"status":"curl_missing"}\n' > "$STAGING_DIR/health.json"
fi

python3 - "$STAGING_DIR" "$BUNDLE_ID" "$TIMESTAMP" "$DOCTOR_EXIT" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
files = sorted(path.name for path in root.iterdir() if path.is_file() and path.name != "manifest.json")
payload = {
    "format": "meufinanceiro-sanitized-diagnostics",
    "version": 1,
    "bundle_id": sys.argv[2],
    "created_at_utc": sys.argv[3],
    "doctor_exit_code": int(sys.argv[4]),
    "files": files,
    "privacy": {
        "contains_env": False,
        "contains_keyring": False,
        "contains_database_dump": False,
        "automatic_upload": False,
    },
}
(root / "manifest.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

forbidden_name=$(find "$STAGING_DIR" -type f \( \
  -name '.env' -o -name 'keyring.json' -o -name '*.dump' -o -name '*.sql' \
  -o -name '*.pem' -o -name '*.key' -o -name '*.p12' -o -name '*.pfx' \
\) -print -quit)
if [[ -n "$forbidden_name" ]]; then
  echo "Arquivo proibido detectado no bundle." >&2
  exit 1
fi

python3 - "$STAGING_DIR" <<'PY'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
patterns = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)postgres(?:ql)?://[^\s/]+@"),
    re.compile(r"(?i)\b(?:POSTGRES_PASSWORD|APP_DATABASE_PASSWORD|DATABASE_URL|ACCESS_TOKEN|REFRESH_TOKEN|CLIENT_SECRET|PRIVATE_KEY)\b\s*[:=]\s*(?!\[REDACTED\])\S+"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
)
for path in root.iterdir():
    if not path.is_file():
        continue
    text = path.read_text(encoding="utf-8", errors="replace")
    for pattern in patterns:
        if pattern.search(text):
            raise SystemExit(f"Conteúdo potencialmente sensível em {path.name}")
PY

tar -C "$TEMP_ROOT" -czf "$ARCHIVE_PATH" "$BUNDLE_ID"
printf '%s\n' "$ARCHIVE_PATH"
