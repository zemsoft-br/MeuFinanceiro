# meufinanceiro-banking-sync

Orquestração provider-neutral, limitada e síncrona da sincronização bancária manual
do MeuFinanceiro, além de projeções locais de lifecycle que não exigem I/O de
provider.

## Responsabilidade

O pacote compõe fronteiras injetadas:

```text
ContextualBankingReadService
ManualSyncStore
SyncFairnessStore                    # extensão estrutural do store canônico
TransactionReconciliationStore       # reconciliação local pós-sync
ConsentLifecycleEvaluator            # projeção temporal somente de fatos locais
```

Fluxo canônico do sincronizador:

```text
begin_manual_sync
  -> mark_sync_running
  -> list_accounts
  -> replace_external_accounts
  -> prepare_sync_cycle
  -> selecionar somente contas ainda pendentes
  -> list_transactions
  -> apply_transaction_page + progresso do ciclo
  -> finish_sync
```

O pacote não conhece SDK, transporte HTTP, credencial, Item ID ou payload específico
de provider.

## Lifecycle local de consentimento

`ConsentLifecycleEvaluator` classifica `consent_expires_at` e o estado local da
conexão sem chamar `BankingProvider`.

Estados:

```text
UNKNOWN
NON_EXPIRING
VALID
EXPIRING
EXPIRED
```

A warning window pertence a `ConsentLifecyclePolicy` e não possui default escondido.
O relógio é injetado, timestamps precisam ser timezone-aware e são comparados em
UTC.

`DISCONNECTED` permanece terminal no eixo operacional: o estado temporal pode ser
preservado para histórico, mas `renewal_required` é sempre `false`.

`REVOKED` nunca é inferido por timestamp. Renovação real, Connect update mode e
qualquer mutação provider-side permanecem fora deste pacote/recorte.

## Limites padrão do sync

```text
max_accounts_per_run = 20
max_pages_per_run = 20
max_records_per_run = 5000
```

Os limites são imutáveis e podem ser reduzidos/injetados em testes ou composição
futura. Não existe retry automático.

## Fairness entre contas

O store canônico mantém um ciclo explícito por conexão e membership por conta local.
Contas concluídas deixam de competir por orçamento no mesmo ciclo.

Para impedir que uma paginação longa monopolize vários runs, cada membership
registra `pages_committed`. O plano ordena contas pendentes por menor quantidade de
páginas já confirmadas; em empate, uma conta com recovery cursor tem prioridade.

Assim, recovery continua favorecido sem impedir progresso eventual de contas menos
atendidas. Nenhum marcador de fairness é codificado no cursor do provider.

## Estratégia inicial de cursor

A sincronização usa full-scan paginado (`changed_since=None`). Um cursor persistido
representa somente um checkpoint de retomada de uma execução incompleta.

Quando a página retornada é terminal (`next_cursor=None`), `apply_transaction_page`
aplica as observações, remove atomicamente eventual cursor persistido e conclui a
membership da conta no ciclo. Assim:

- falha de página preserva checkpoint e progresso anterior;
- uma execução concluída reinicia por full-scan em um novo ciclo futuro;
- repetição continua idempotente por fingerprint/observação;
- nenhuma estratégia incremental é inferida prematuramente.

## Escopo de contas

Todas as contas normalizadas são persistidas como `external_accounts`.

Neste estágio, páginas de transações são solicitadas somente para contas `BANK` e
`CREDIT`. Outros tipos permanecem disponíveis para recortes posteriores de
investimentos, empréstimos ou capacidades específicas.

O scheduler persiste somente o UUID local de `external_accounts`, escopo
residência/conexão, estado de membership e contador de páginas. O identificador
externo não é duplicado nas tabelas de fairness.

## Reconciliação local explícita após o sync

`ManualBankingSyncService.run` continua responsável exclusivamente pelo sync.

A composição opcional:

```text
ManualBankingSyncReconciliationService
```

recebe um `ManualSyncRunner` e um `TransactionReconciliationStore` e executa:

```text
manual_sync.run(...)
  -> SUCCEEDED ou PARTIAL?
       reconcile_transaction_observations(...)
```

`FAILED`, `RUNNING`/`ALREADY_RUNNING` e `CANCELLED` não disparam reconciliação.

Um run terminal replayado continua elegível quando seu status persistido é
`SUCCEEDED` ou `PARTIAL`. Isso permite retentar somente o post-processing local com
a mesma `idempotency_key`, sem exigir nova leitura do provider.

A composição executa no máximo **um batch** de reconciliação por chamada:

```text
default = 500 observações
máximo = 1000 observações
```

`has_more=true` permanece no resultado e não gera loop automático.

Sync e reconciliação são transações separadas. Se a reconciliação falhar depois do
sync terminal, o run já confirmado não é reaberto nem modificado; a fronteira lança
apenas `ManualSyncReconciliationExecutionError` sanitizado.

## Resultado

`ManualSyncResult` retorna somente IDs locais e contagens operacionais. O `repr`
omite o UUID do run e não contém cursor, IDs externos, valores financeiros ou
descrição de transação.

`ManualSyncReconciliationResult` agrega o `ManualSyncResult` e, quando elegível, o
`TransactionReconciliationResult` local já redigido. Seu `repr` também omite o UUID
do run e qualquer material externo/financeiro.

`ConsentLifecycleResult` não contém identificadores. Seu `repr` expõe apenas o
estado temporal, `renewal_required` e se a conexão está terminal.

## Fora do escopo

- FastAPI;
- Flutter;
- worker/fila/polling;
- refresh manual do provider;
- criação ou alteração de lançamentos financeiros do usuário;
- fuzzy matching entre identidades;
- loop automático para drenar reconciliação;
- `changed_since` incremental;
- recovery automático de run órfão;
- cartões/faturas;
- investimentos/empréstimos;
- desconexão;
- renovação/mutação de consentimento no provider;
- webhooks.
