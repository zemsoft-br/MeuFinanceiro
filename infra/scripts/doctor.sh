#!/usr/bin/env sh
set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
BASE_URL=${MEUFINANCEIRO_BASE_URL:-http://127.0.0.1:8080}
FAILURES=0
WARNINGS=0

ok() {
  printf 'OK   %s\n' "$1"
}

warn() {
  printf 'WARN %s\n' "$1"
  WARNINGS=$((WARNINGS + 1))
}

fail() {
  printf 'FAIL %s\n' "$1" >&2
  FAILURES=$((FAILURES + 1))
}

has_command() {
  command -v "$1" >/dev/null 2>&1
}

check_command() {
  if has_command "$1"; then
    ok "$1 disponível"
  else
    fail "$1 não encontrado"
  fi
}

printf 'MeuFinanceiro doctor (somente leitura)\n'
printf 'Raiz: <REPOSITORY>\n'
printf 'Endpoint: %s\n' "$BASE_URL"

check_command git
check_command docker
check_command curl

if has_command git; then
  if git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    ok "checkout Git válido"
    branch=$(git -C "$ROOT_DIR" symbolic-ref --quiet --short HEAD 2>/dev/null || true)
    if [ "$branch" = "develop" ]; then
      ok "branch develop"
    elif [ -n "$branch" ]; then
      warn "branch atual é $branch; a instalação comum usa develop"
    else
      warn "checkout detached"
    fi
    if git -C "$ROOT_DIR" diff --quiet && git -C "$ROOT_DIR" diff --cached --quiet; then
      ok "checkout sem alterações rastreadas"
    else
      warn "checkout possui alterações rastreadas"
    fi
  else
    fail "a raiz não é um checkout Git"
  fi
fi

if [ -f "$ROOT_DIR/compose.yaml" ]; then
  ok "compose.yaml presente"
else
  fail "compose.yaml ausente"
fi

if [ -f "$ROOT_DIR/.env" ]; then
  ok ".env presente (conteúdo não lido)"
else
  warn ".env ausente; a instalação comum ainda pode não ter sido inicializada"
fi

if [ -f "$ROOT_DIR/.secrets/keyring.json" ]; then
  ok "keyring presente (conteúdo não lido)"
else
  warn "keyring ausente; a instalação comum ainda pode não ter sido inicializada"
fi

if has_command docker; then
  if docker version --format '{{.Server.Version}}' >/dev/null 2>&1; then
    ok "Docker Engine acessível"
  else
    fail "Docker Engine indisponível"
  fi

  if docker compose version >/dev/null 2>&1; then
    ok "Docker Compose v2 disponível"
  else
    fail "Docker Compose v2 não encontrado"
  fi

  if [ -f "$ROOT_DIR/compose.yaml" ] && [ -f "$ROOT_DIR/.env" ]; then
    if docker compose --project-directory "$ROOT_DIR" --env-file "$ROOT_DIR/.env" \
      -f "$ROOT_DIR/compose.yaml" config --services >/dev/null 2>&1; then
      ok "contrato Compose resolvido"
    else
      fail "contrato Compose inválido ou configuração incompleta"
    fi

    running=$(docker compose --project-directory "$ROOT_DIR" --env-file "$ROOT_DIR/.env" \
      -f "$ROOT_DIR/compose.yaml" ps --status running -q 2>/dev/null | awk 'NF' | wc -l | tr -d ' ')
    if [ "${running:-0}" -gt 0 ]; then
      ok "stack possui serviços em execução"
    else
      warn "nenhum serviço da stack está em execução"
    fi
  fi
fi

if has_command curl; then
  if curl --fail --silent --show-error --max-time 4 \
    "$BASE_URL/api/v1/health/ready" >/dev/null 2>&1; then
    ok "API readiness saudável"
  else
    warn "API readiness indisponível em $BASE_URL"
  fi
fi

printf 'SUMMARY failures=%s warnings=%s\n' "$FAILURES" "$WARNINGS"

if [ "$FAILURES" -gt 0 ]; then
  exit 1
fi
exit 0
