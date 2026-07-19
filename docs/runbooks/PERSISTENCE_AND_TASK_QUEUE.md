# Persistência, migrações e fila de tarefas

Este runbook cobre a fundação PostgreSQL da API e do Worker. Não contém procedimentos de domínio financeiro.

## Serviços

A ordem de inicialização do Compose é:

```text
postgres -> db-bootstrap -> migrate -> api/worker -> caddy
```

- `postgres`: banco local e fonte de verdade;
- `db-bootstrap`: cria ou reconcilia a role sem privilégios usada em runtime;
- `migrate`: aplica Alembic até `head` e encerra com código zero;
- `api`: só inicia após migração concluída;
- `worker`: só inicia após migração concluída.

`db-bootstrap` e `migrate` são serviços one-shot. Permanecerem em estado `Exited (0)` é esperado.

## Credenciais locais

O `.env` contém duas credenciais independentes:

```text
POSTGRES_USER / POSTGRES_PASSWORD
APP_DATABASE_USER / APP_DATABASE_PASSWORD
```

A primeira é administrativa e só deve ser usada pelo PostgreSQL, bootstrap e migração. A segunda é usada pela API e pelo Worker. Os scripts `dev-up` geram ambas com CSPRNG e preservam o `.env` privado.

`APP_DATABASE_USER` deve ser diferente da role administrativa; o bootstrap aborta antes de qualquer mutação quando há colisão.

Nunca use credenciais reais ou reutilizadas.

## Inicialização limpa

Linux, macOS ou WSL:

```bash
./infra/scripts/dev-up.sh
```

Windows PowerShell:

```powershell
./infra/scripts/dev-up.ps1
```

Os scripts criam a configuração segura, aplicam as migrações e executam um smoke test que:

1. valida readiness da API e do Worker;
2. enfileira a mesma chave duas vezes e confirma o mesmo `task_id`;
3. aguarda o Worker concluir a tarefa demonstrativa.

## Migrações

Aplicar até `head`:

```bash
docker compose run --rm migrate
```

Testar downgrade da fundação somente em ambiente descartável:

```bash
docker compose run --rm migrate \
  python -m meufinanceiro_persistence.migrate downgrade-base
```

O downgrade remove as tabelas do schema `infra`. Não execute em ambiente com dados que precisem ser preservados.

## Health checks

API:

```text
GET /api/v1/health/live
GET /api/v1/health/ready
```

Worker, dentro da rede do Compose:

```text
GET /health/live
GET /health/ready
```

Readiness retorna separadamente:

- `process`: processo respondeu;
- `database`: round-trip `SELECT 1`;
- `schema`: revisão Alembic atual comparada ao `head` esperado.

`schema=outdated` ou `database=unavailable` produz HTTP 503.

## Contrato da fila

Tabela principal:

```text
infra.task_queue
```

Estados:

```text
pending -> running -> succeeded
                  -> pending (retry)
                  -> failed
                  -> cancelled
```

Campos operacionais principais:

- `idempotency_key`: impede enqueue duplicado;
- `attempts` e `max_attempts`: controlam retry;
- `available_at`: agenda a próxima tentativa;
- `locked_by`, `locked_at`, `lease_token`, `lease_expires_at`: propriedade temporária;
- `last_error`: erro sanitizado e truncado;
- `correlation_id`: correlação entre logs e operações;
- `completed_at`: término auditável.

## Recuperação de tarefa abandonada

Uma tarefa `running` tem o lease renovado periodicamente enquanto o handler permanece em execução. Todos os cálculos de validade usam o relógio do PostgreSQL, não o relógio local do container.

Se o Worker parar de renovar e o lease expirar, outro Worker pode reservar a tarefa quando ainda houver tentativas. A nova reserva recebe outro `lease_token`; o Worker antigo não pode concluir a tarefa.

Quando o lease expira após a última tentativa, o Worker a move para `failed` com erro operacional estável.

Não edite manualmente os campos de lease em ambiente real. A alteração direta é permitida apenas nos testes descartáveis.

## Retry e efeitos idempotentes

O Worker calcula backoff exponencial limitado. O enqueue idempotente evita duas linhas para a mesma chave, mas não garante exactly-once para efeitos externos.

Cada handler futuro deve:

1. usar chave de idempotência própria;
2. preferir efeito e marcação na mesma transação quando o efeito estiver no PostgreSQL;
3. tratar resposta repetida de provedores externos;
4. nunca registrar payload sensível integralmente em erro ou log.

O handler `demo.echo` usa `infra.demo_task_effects.task_id` como chave única para demonstrar o padrão.

## Diagnóstico

Estado dos serviços:

```bash
docker compose ps --all
```

Logs sem incluir `.env` ou keyring:

```bash
docker compose logs --tail 200 api worker migrate db-bootstrap postgres
```

Executar o smoke novamente:

```bash
./tests/smoke/compose-smoke.sh
```

Ver uma tarefa pelo ID:

```bash
docker compose exec -T api \
  python -m meufinanceiro_persistence.cli get --task-id <uuid>
```

## Backup e restore

O schema `infra` faz parte do mesmo PostgreSQL e deve ser incluído no backup integral. Banco e keyring precisam ser restaurados de forma coordenada, conforme o ADR-0005. Não restaure apenas a tabela de tarefas sem avaliar o estado dos módulos que produzirão os efeitos futuros.
