# Atualização segura e rollback controlado

## Objetivo

Atualizar a instalação comum baseada em código-fonte preservando o volume PostgreSQL, `.env` e keyring. O fluxo cria e verifica um backup coordenado antes de alterar containers ou imagens e só avança o checkout principal depois que o target passa no smoke test.

Este runbook cobre a fundação local. Não autoriza atualização de produção, HML, domínio, DNS, Cloudflare ou Caddy público.

## Limite do rollback

O Compose aplica `db-bootstrap` e `migrate upgrade` antes de iniciar API e Worker. O downgrade disponível na fundação remove tabelas do schema `infra` e não é apropriado para uma instalação que precise preservar dados.

Por isso, existem dois resultados de falha:

- `ROLLED_BACK`: a revisão Alembic não mudou; o operador reconstruiu o commit anterior e confirmou o smoke;
- `ROLLBACK_REQUIRES_COORDINATED_RESTORE`: a revisão mudou ou não pôde ser confirmada; o operador não executou downgrade, não removeu volume e não restaurou o backup automaticamente.

O segundo estado exige uma futura restauração destrutiva explicitamente autorizada. Preserve o bundle indicado pelo estado local.

## Conteúdo sensível

Toda atualização exige um bundle da instalação comum contendo dump, `.env` e keyring. Esse bundle possui senhas e chave mestra.

- escolha armazenamento criptografado;
- nunca versione `.backups/` ou `.updates/`;
- nunca anexe bundle, `.env`, keyring ou dump a issues, PRs ou artifacts;
- não compartilhe logs sem revisão.

O manifesto em `.updates/<update-id>/state.json` é sanitizado. Ele registra commits, revisões Alembic, ID do bundle, fingerprint do volume e estado, sem senha, URL de banco, material criptográfico ou conteúdo do dump.

## Pré-requisitos

- instalação comum saudável;
- checkout limpo na branch `develop`;
- Docker e Docker Compose v2;
- Git;
- Python 3 no fluxo Unix;
- `.env` e `.secrets/keyring.json` existentes;
- target Git já publicado e alcançável por fast-forward;
- destino criptografado com espaço para o backup.

Confirme antes de iniciar:

```text
git status --short
docker compose ps --all
```

Não prossiga com alterações rastreadas no checkout.

## Linux, macOS ou WSL 2

Atualize as referências remotas e execute:

```bash
bash infra/scripts/update-foundation.sh \
  --target-ref origin/develop \
  --backup-dir /caminho/criptografado/meufinanceiro \
  --acknowledge-sensitive
```

O operador:

1. adquire lock exclusivo em `.updates/update.lock`;
2. valida checkout, target fast-forward, configuração, keyring, volume e revisão Alembic;
3. cria e restaura o backup em PostgreSQL descartável;
4. prepara o target em worktree temporário;
5. constrói as imagens antes de recriar a stack;
6. executa `docker compose up --detach --wait` no mesmo projeto e volume;
7. executa smoke de API, Worker e Flutter Web/PWA;
8. compara hashes de `.env` e keyring e fingerprint do volume;
9. avança o checkout principal por fast-forward somente após sucesso;
10. remove worktree, lock e temporários, preservando o bundle.

## Windows PowerShell

```powershell
& .\infra\scripts\update-foundation.ps1 `
  -TargetRef origin/develop `
  -BackupDirectory 'D:\BackupsCriptografados\MeuFinanceiro' `
  -AcknowledgeSensitive
```

O contrato de segurança é o mesmo do operador Unix. O script usa captura separada de stdout/stderr para processos nativos e não depende de Bash ou Python no host Windows.

## Target já aplicado

Quando o target resolve para o commit atual, o operador termina de forma idempotente com estado:

```text
APPLIED / target_already_applied
```

Nenhum backup novo, build ou restart é necessário nesse caso.

## Estados locais

Cada execução cria:

```text
.updates/update-<utc>-<random>/state.json
```

Estados possíveis:

- `FAILED_PRECHECK`: nenhuma atualização foi aplicada;
- `PREPARED`: backup criado e restaurado; target ainda não aplicado;
- `APPLIED`: target saudável e checkout avançado;
- `ROLLED_BACK`: target falhou, schema não mudou e commit anterior voltou saudável;
- `ROLLBACK_REQUIRES_COORDINATED_RESTORE`: possível avanço de schema bloqueou rollback automático.

O arquivo é evidência local, não um log completo. Caminhos absolutos e segredos não são armazenados.

## Quando o rollback automático é executado

Se build do target falhar, a stack original não é alterada e o resultado é `FAILED_PRECHECK`.

Se a falha ocorrer depois do startup do target, o operador consulta novamente `alembic_version`:

- revisão igual à inicial: reconstrói o commit anterior e executa smoke;
- revisão diferente ou indisponível: para API, Worker, Web e Caddy do target, mantém PostgreSQL e volume intactos e exige recuperação coordenada.

O operador nunca executa:

```text
docker compose down --volumes
docker volume rm
alembic downgrade
```

## Recuperação coordenada necessária

Ao receber `ROLLBACK_REQUIRES_COORDINATED_RESTORE`:

1. não apague `.updates/` nem o bundle informado;
2. não tente iniciar versões aleatórias do código;
3. não execute downgrade Alembic;
4. preserve o PostgreSQL e colete apenas diagnóstico sanitizado;
5. aguarde o procedimento separado de restauração destrutiva real.

A verificação descartável descrita em [Backup coordenado e restauração verificável](BACKUP_AND_RESTORE.md) não altera a instalação e não substitui esse procedimento futuro.

## Concorrência e limpeza

- somente uma atualização pode manter `.updates/update.lock`;
- target é resolvido para commit imutável;
- worktree fica em diretório temporário do sistema;
- cleanup não remove o bundle;
- falha de cleanup não autoriza remover volumes;
- `.updates/` é ignorado pelo Git apenas contra commit acidental, não como proteção criptográfica.

## Fora do escopo

- imagens ou releases publicadas;
- atualização do ambiente demo;
- restauração destrutiva do bundle sobre a instalação comum;
- downgrade automático;
- migração entre hosts;
- rotação de credenciais ou keyring;
- produção, HML ou infraestrutura pública.
