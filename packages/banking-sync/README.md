# meufinanceiro-banking-sync

Orquestração provider-neutral, limitada e síncrona da sincronização bancária manual do MeuFinanceiro.

## Responsabilidade

O pacote compõe fronteiras injetadas:

```text
ContextualBankingReadService
ManualSyncStore
SyncFairnessStore        # extensão estrutural do store canônico
```

Fluxo canônico:

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

O pacote não conhece SDK, transporte HTTP, credencial, Item ID ou payload específico de provider.

## Limites padrão

```text
max_accounts_per_run = 20
max_pages_per_run = 20
max_records_per_run = 5000
```

Os limites são imutáveis e podem ser reduzidos/injetados em testes ou composição futura. Não existe retry automático.

## Fairness entre contas

O store canônico mantém um ciclo explícito por conexão e membership por conta local. Contas concluídas deixam de competir por orçamento no mesmo ciclo.

Para impedir que uma paginação longa monopolize vários runs, cada membership registra `pages_committed`. O plano ordena contas pendentes por menor quantidade de páginas já confirmadas; em empate, uma conta com recovery cursor tem prioridade.

Assim, recovery continua favorecido sem impedir progresso eventual de contas menos atendidas. Nenhum marcador de fairness é codificado no cursor do provider.

## Estratégia inicial de cursor

A sincronização usa full-scan paginado (`changed_since=None`). Um cursor persistido representa somente um checkpoint de retomada de uma execução incompleta.

Quando a página retornada é terminal (`next_cursor=None`), `apply_transaction_page` aplica as observações, remove atomicamente eventual cursor persistido e conclui a membership da conta no ciclo. Assim:

- falha de página preserva checkpoint e progresso anterior;
- uma execução concluída reinicia por full-scan em um novo ciclo futuro;
- repetição continua idempotente por fingerprint/observação;
- nenhuma estratégia incremental é inferida prematuramente.

## Escopo de contas

Todas as contas normalizadas são persistidas como `external_accounts`.

Neste estágio, páginas de transações são solicitadas somente para contas `BANK` e `CREDIT`. Outros tipos permanecem disponíveis para recortes posteriores de investimentos, empréstimos ou capacidades específicas.

O scheduler persiste somente o UUID local de `external_accounts`, escopo residência/conexão, estado de membership e contador de páginas. O identificador externo não é duplicado nas tabelas de fairness.

## Resultado

`ManualSyncResult` retorna somente IDs locais e contagens operacionais. O `repr` omite o UUID do run e não contém cursor, IDs externos, valores financeiros ou descrição de transação.

## Fora do escopo

- FastAPI;
- Flutter;
- worker/fila/polling;
- refresh manual do provider;
- reconciliação com lançamentos financeiros;
- `changed_since` incremental;
- recovery automático de run órfão;
- cartões/faturas;
- investimentos/empréstimos;
- desconexão/consentimento;
- webhooks.