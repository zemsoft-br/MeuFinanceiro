# meufinanceiro-banking-sync

Orquestração provider-neutral, limitada e síncrona da primeira sincronização bancária manual do MeuFinanceiro.

## Responsabilidade

O pacote compõe duas fronteiras injetadas:

```text
ContextualBankingReadService
ManualSyncStore
```

Fluxo:

```text
begin_manual_sync
  -> mark_sync_running
  -> list_accounts
  -> replace_external_accounts
  -> priorizar contas com cursor pendente
  -> list_transactions
  -> apply_transaction_page
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

## Estratégia inicial de cursor

A sincronização usa full-scan paginado (`changed_since=None`). Um cursor persistido representa somente um checkpoint de retomada de uma execução incompleta.

Quando a página retornada é terminal (`next_cursor=None`), `apply_transaction_page` aplica as observações e remove atomicamente eventual cursor persistido da conta. Assim:

- falha de página preserva o checkpoint anterior;
- uma execução concluída reinicia por full-scan numa sincronização manual futura;
- repetição continua idempotente por fingerprint/observação;
- nenhuma estratégia incremental é inferida prematuramente.

## Escopo de contas

Todas as contas normalizadas são persistidas como `external_accounts`.

Neste primeiro recorte, páginas de transações são solicitadas somente para contas `BANK` e `CREDIT`. Outros tipos permanecem disponíveis para recortes posteriores de investimentos, empréstimos ou capacidades específicas.

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
