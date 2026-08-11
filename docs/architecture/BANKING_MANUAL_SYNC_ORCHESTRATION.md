# Orquestração da sincronização bancária manual

Status: **fundação da Epic #63 / issue #115, estendida pelas #117 e #121**.

## Objetivo

Executar sincronização manual de contas e transações de forma provider-neutral, limitada, retomável e fail-closed, sem criar endpoint, worker ou lançamento financeiro do domínio.

## Fluxo canônico

```text
begin_manual_sync
  -> mark_sync_running
  -> ContextualBankingReadService.list_accounts
  -> replace_external_accounts
  -> prepare_sync_cycle
  -> selecionar contas ativas ainda pendentes
  -> ContextualBankingReadService.list_transactions
  -> apply_transaction_page
  -> finish_sync
```

O pacote responsável é `packages/banking-sync`. Ele depende somente de `meufinanceiro-banking` e `meufinanceiro-persistence`; não importa Pluggy, HTTP, FastAPI ou worker.

## Escopo confiável

As operações públicas recebem somente IDs locais:

```text
installation_id
residence_id
connection_id
idempotency_key
```

Item ID, Client User ID, credenciais, token e payload provider-specific não fazem parte da API do pacote.

## Idempotência e single-flight

`begin_manual_sync` continua sendo a autoridade para idempotência e single-flight:

- chave já terminal retorna replay local sem provider I/O;
- run já `running` não é reiniciado automaticamente;
- outra chave concorrente continua bloqueada pelo PostgreSQL;
- recovery automático de processo morto permanece fora deste estágio.

A retomada de uma execução parcial usa uma nova operação lógica e os checkpoints locais persistidos.

## Snapshot de contas

`ExternalAccount` é convertido para `ExternalAccountSnapshot` e persistido antes de qualquer página de transações.

Somente:

```text
BANK
CREDIT
```

entram no fluxo de transações. `OTHER`, `INVESTMENT` e `LOAN` podem permanecer no catálogo local, sem `list_transactions` neste estágio.

Ausência em um snapshot não apaga automaticamente a conta nem infere desconexão.

## Full-scan e recovery cursor

A estratégia inicial continua:

```text
changed_since = None
```

Portanto o ciclo é um full-scan paginado. `sync_cursors` representa exclusivamente checkpoint de paginação incompleta.

### Página não terminal

Quando `next_cursor` contém valor:

1. a página é normalizada;
2. observações e cursor são confirmados na mesma transação;
3. no modo cycle-aware, `pages_committed` da membership também avança nessa transação;
4. uma operação posterior pode retomar pelo cursor.

### Página terminal

Quando `next_cursor=None`, `apply_transaction_page`:

1. aplica observações;
2. remove eventual recovery cursor;
3. avança `pages_committed`;
4. marca a membership da conta como concluída;
5. se era a última conta ativa pendente, conclui o ciclo;
6. confirma tudo no mesmo commit PostgreSQL.

Falha em qualquer etapa preserva o checkpoint e o progresso anterior por rollback.

## Fairness persistente da #117

A limitação de continuidade originalmente registrada na #115 foi resolvida pela #117 com estado explícito:

```text
integrations.sync_cycles
integrations.sync_cycle_accounts
```

O cursor do provider permanece opaco e não recebe sentinela local.

O scheduler persiste por conta do ciclo:

```text
external_account_record_id  # UUID local
active_in_latest_snapshot
pages_committed
completed_at
```

O plano corrente ordena contas pendentes por:

```text
1. menor pages_committed
2. recovery cursor primeiro em caso de empate
3. ordem local estável
```

O orquestrador preserva essa ordem antes de aplicar os limites. Contas concluídas deixam de competir por orçamento no ciclo; uma conta com paginação longa também não pode monopolizar indefinidamente contas menos atendidas.

A modelagem completa está em `docs/architecture/BANKING_SYNC_FAIRNESS.md`.

## Normalização das transações

Mapeamento explícito:

```text
TransactionStatus.CONFIRMED -> StoredTransactionObservationStatus.CONFIRMED
TransactionStatus.PENDING   -> StoredTransactionObservationStatus.PENDING
TransactionStatus.INFERRED  -> StoredTransactionObservationStatus.INFERRED
TransactionStatus.DELETED   -> StoredTransactionObservationStatus.DELETED
```

`page.retrieved_at` é usado como `observed_at`.

Ainda não são materializados pelo orquestrador:

- `bill_reference`;
- `installment_metadata`.

## Limites

Defaults:

```text
max_accounts_per_run = 20
max_pages_per_run = 20
max_records_per_run = 5000
```

Os limites continuam sendo *safety ceilings* por run. A diferença após #117 é que o estado persistente distribui progresso entre múltiplos runs.

Se uma página já recebida ultrapassaria o orçamento restante de registros, ela não é persistida e o checkpoint anterior permanece intacto. Em uma nova operação o orçamento por run recomeça sem perder o cursor confirmado anterior.

Atingir limite encerra o run como `partial`; não existe retry automático nesta camada.

## Erros

`BankingProviderError.category` é convertido para `StoredSyncErrorCategory` neutro.

Persistência permitida para falha provider:

```text
error_category
provider_reason_code sanitizado
```

Não são persistidos em diagnóstico:

- mensagem livre;
- URL;
- headers;
- request/response body;
- traceback;
- credencial;
- cursor.

Erro provider antes de qualquer página confirmada encerra como `failed`; depois de página confirmada, como `partial`.

Falhas inesperadas são reduzidas a `INTERNAL`. Se o fechamento do run também falhar, a fronteira lança somente `ManualSyncExecutionError` sanitizado.

## Resultado local

`ManualSyncResult` contém somente:

```text
sync_run_id local
status
records_seen
records_applied
accounts_seen
pages_committed
stop_reason
```

Seu `repr` não mostra UUID do run, cursor, IDs externos ou material financeiro.

## Composição explícita com reconciliação — #121

A #121 adiciona uma fronteira **separada**:

```text
ManualBankingSyncReconciliationService
```

Ela não altera `ManualBankingSyncService.run` e não injeta reconciliação como side effect oculto dentro do sincronizador.

Fluxo da composição manual:

```text
ManualBankingSyncService.run(...)
  -> sync_result local terminal ou running/failed
  -> se status = SUCCEEDED ou PARTIAL:
       reconcile_transaction_observations(..., limit=N)
  -> retornar ManualSyncReconciliationResult
```

Somente `SUCCEEDED` e `PARTIAL` são elegíveis porque podem representar observações já confirmadas localmente.

Não há reconciliação quando o resultado está:

```text
FAILED
RUNNING / ALREADY_RUNNING
CANCELLED
```

Isso evita post-processing concorrente enquanto o sync ainda está em execução e não atribui significado a um run que falhou sem estado local utilizável.

### Recovery por replay

Uma chave idempotente terminal continua sendo valiosa depois do sync:

```text
sync confirma observações
  -> sync run termina
  -> reconciliação falha
  -> repetir a mesma idempotency_key
  -> ManualBankingSyncService retorna REPLAYED sem provider I/O
  -> a composição tenta novamente a reconciliação local
```

O sync run terminal não é reaberto, reescrito ou compensado por falha posterior da reconciliação.

### Limite da reconciliação

Por chamada da composição:

```text
default = 500 observações
máximo = 1000 observações
```

Existe **no máximo um batch** de reconciliação por chamada.

Se `TransactionReconciliationResult.has_more` for `true`, o backlog permanece explícito para uma nova invocação. Não existe loop automático para drenar toda a fila local.

### Fronteiras transacionais

Sync e reconciliação são commits PostgreSQL separados:

```text
provider I/O + persistência do sync
  -> COMMIT do sync run
  -> reconciliação local
  -> COMMIT próprio
```

Não há tentativa de criar uma transação distribuída entre provider I/O e PostgreSQL.

Falha da reconciliação é reduzida a `ManualSyncReconciliationExecutionError` sanitizado. O run de sync já terminal permanece intacto e pode ser reutilizado por replay para recovery.

### Resultado composto

`ManualSyncReconciliationResult` contém apenas:

```text
ManualSyncResult
TransactionReconciliationResult | None
```

Os dois contratos já são redigidos. O `repr` composto não mostra UUID do sync run nem material externo/financeiro.

A reconciliação canônica em si está descrita em `docs/architecture/BANKING_TRANSACTION_RECONCILIATION.md`.

## Segurança

A orquestração não executa por conta própria:

- criação de transporte;
- leitura de credencial;
- request refresh;
- PATCH/DELETE de Item;
- fila, polling ou background task;
- endpoint HTTP;
- UI Flutter;
- criação/alteração de lançamento financeiro do usuário.

A implementação concreta do leitor continua responsável pelas garantias contextuais da #80/#81; a persistência mantém RLS por residência.

## Fora do escopo

- sync incremental por `changed_since`;
- recovery automático de run órfão;
- merge entre observações e lançamentos financeiros;
- inferência de deleção por ausência;
- loop automático para drenar reconciliação;
- cartões/faturas/parcelas;
- investimentos e empréstimos;
- desconexão e consentimento;
- webhooks;
- sincronização automática.

## Validação

Os testes são sintéticos. GitHub Actions não é gate operacional deste projeto. Qualquer validação não efetivamente executada nesta sessão permanece declarada como não executada.