# Orquestração da sincronização bancária manual

Status: **implementação da Epic #63 / issue #115**.

## Objetivo

Este recorte compõe as fundações já entregues para executar a primeira sincronização
manual de contas e transações de forma provider-neutral, limitada e fail-closed.

A fronteira não cria endpoint, worker ou lançamento financeiro do domínio.

## Fluxo

```text
begin_manual_sync
  -> mark_sync_running
  -> ContextualBankingReadService.list_accounts
  -> replace_external_accounts
  -> priorizar contas com recovery cursor
  -> ContextualBankingReadService.list_transactions
  -> apply_transaction_page
  -> finish_sync
```

O pacote responsável é:

```text
packages/banking-sync
```

Ele depende somente de `meufinanceiro-banking` e
`meufinanceiro-persistence`. Não importa Pluggy, HTTP, FastAPI ou worker.

O executor Pluggy contextual da #80/#81 pode satisfazer o protocol de leitura por
tipagem estrutural, mas a orquestração não conhece essa implementação concreta.

## Escopo confiável

Todas as operações públicas recebem somente IDs locais:

```text
installation_id
residence_id
connection_id
idempotency_key
```

Item ID, Client User ID, credenciais, token e payload provider-specific não fazem
parte da API do pacote.

A resolução da conexão e da residência continua delegada às fronteiras já protegidas
por RLS.

## Idempotência e single-flight

`begin_manual_sync` continua sendo a autoridade para idempotência e single-flight.

Regras da orquestração:

- uma chave já terminal é replay local e não executa provider;
- um run já `running` não é reiniciado automaticamente;
- outra chave concorrente continua bloqueada pelo índice parcial PostgreSQL;
- recovery automático de processo morto não pertence a este recorte.

A retomada de uma execução parcialmente concluída usa **uma nova operação lógica** e o
cursor persistido da conta.

## Snapshot de contas

O provider-neutral `ExternalAccount` é convertido para `ExternalAccountSnapshot`.
Todas as contas observadas são persistidas de forma minimizada.

Neste estágio, somente tipos:

```text
BANK
CREDIT
```

entram na leitura de transações. `OTHER`, `INVESTMENT` e `LOAN` podem permanecer no
catálogo local, mas não causam chamadas de transações.

A ausência de uma conta em um snapshot não provoca remoção automática.

## Full-scan e recovery cursor

A estratégia inicial é deliberadamente simples:

```text
changed_since = None
```

Portanto cada sincronização completa é um full-scan paginado. Um `sync_cursor`
persistido significa apenas que um full-scan anterior foi interrompido depois de uma
página confirmada e pode ser retomado.

Contas que possuem esse checkpoint são processadas antes das contas sem cursor.

### Página não terminal

Quando `ExternalPage.next_cursor` contém valor:

1. a página é normalizada;
2. observações e cursor são confirmados na mesma transação;
3. uma execução posterior pode retomar desse cursor se o run terminar como `partial`.

### Página terminal

Quando:

```text
next_cursor = None
```

`apply_transaction_page`:

1. aplica as observações da página;
2. remove, na mesma transação, eventual `sync_cursor` da conta;
3. deixa a ausência da linha representar full-scan concluído.

A coluna `sync_cursors.cursor` continua `NOT NULL`; não há migration nova para essa
semântica.

Se a página terminal falhar, a transação faz rollback e o checkpoint anterior é
preservado.

Uma sincronização futura, sem recovery cursor, inicia novo full-scan. Estratégia
incremental por `changed_since` será desenhada separadamente.

## Normalização das transações

O orquestrador aceita somente `ExternalTransaction` do contrato neutro e converte
explicitamente:

```text
TransactionStatus.CONFIRMED -> StoredTransactionObservationStatus.CONFIRMED
TransactionStatus.PENDING   -> StoredTransactionObservationStatus.PENDING
TransactionStatus.INFERRED  -> StoredTransactionObservationStatus.INFERRED
TransactionStatus.DELETED   -> StoredTransactionObservationStatus.DELETED
```

`page.retrieved_at` é usado como `observed_at` da observação persistida.

Neste recorte não são persistidos pelo orquestrador:

- `bill_reference`;
- `installment_metadata`.

Esses campos exigirão modelagem específica junto do estágio de cartões/faturas.

## Limites

Defaults:

```text
max_accounts_per_run = 20
max_pages_per_run = 20
max_records_per_run = 5000
```

Os limites são *safety ceilings* por execução lógica, e não um escalonador persistente
entre contas.

Os limites são verificados antes da próxima chamada externa sempre que o tamanho já é
conhecido.

Se uma página recebida ultrapassaria o limite restante de registros, ela não é
persistida e o checkpoint anterior permanece intacto.

Atingir limite termina o run como `partial`; não há retry automático na camada de
orquestração.

### Limitação conhecida de continuidade entre contas

O estado persistido deste recorte sabe distinguir apenas uma conta com full-scan
**interrompido** (possui `sync_cursor`) de uma conta **sem checkpoint**. Depois que uma
conta alcança página terminal, seu cursor é removido e ela volta a ser indistinguível,
para a próxima operação lógica, de uma conta que ainda não começou um novo full-scan.

Consequência: se os limites globais forem atingidos exatamente depois de concluir
contas que aparecem antes de outras no snapshot do provider, uma execução posterior
pode voltar a escanear essas contas antes de alcançar as restantes. O comportamento é
bounded e idempotente, mas este estágio **não promete fairness ou progresso global
entre todas as contas ao longo de múltiplos runs**.

Não é usado cursor sentinela local para contornar isso, porque o cursor é material
opaco do provider. A solução correta exige estado persistido explícito de progresso ou
uma estratégia incremental/fair-scheduling própria, que fica para issue separada antes
de transformar esta fundação em sincronização automática.

Na prática, o limite protege a execução atual; ele não deve ser interpretado como uma
garantia de varredura eventual para cardinalidades acima do teto configurado.

## Erros

`BankingProviderError.category` é convertido explicitamente para o enum neutro
`StoredSyncErrorCategory` correspondente.

Persistência permitida para falha provider:

```text
error_category
provider_reason_code
```

Não são persistidos:

- mensagem livre;
- URL;
- headers;
- request/response body;
- traceback;
- credencial;
- cursor em diagnóstico público.

Erro provider antes de qualquer página confirmada termina como `failed`. Depois de ao
menos uma página confirmada, termina como `partial`.

Falhas inesperadas são reduzidas a `INTERNAL`. Se nem o fechamento do run puder ser
persistido, a API do pacote lança somente `ManualSyncExecutionError` sanitizado.

## Resultado local

`ManualSyncResult` contém:

```text
sync_run_id local
status
records_seen
records_applied
accounts_seen
pages_committed
stop_reason
```

Seu `repr` não mostra o UUID do run nem material financeiro/provider-specific.

## Segurança

O recorte não executa por conta própria:

- criação de transporte;
- leitura de credencial;
- request refresh;
- PATCH/DELETE de Item;
- fila, polling ou background task;
- endpoint HTTP;
- UI Flutter;
- criação/alteração de lançamento financeiro do usuário.

A implementação concreta do leitor continua responsável pelas garantias contextuais
da #80/#81.

## Fora do escopo

- sync incremental por `changed_since`;
- recovery automático de run órfão;
- fairness/escalonamento persistente entre contas através de múltiplos runs;
- reconciliação entre observações e lançamentos financeiros;
- inferência de deleção por ausência;
- cartões/faturas/parcelas;
- investimentos e empréstimos;
- desconexão e consentimento;
- webhooks;
- sincronização automática.

## Validação

Os testes deste recorte são sintéticos. A configuração de Quality passa a incluir o
novo pacote, mas GitHub Actions não é tratado como gate operacional neste projeto por
decisão do mantenedor.

Nesta sessão, qualquer validação não efetivamente executada deve permanecer declarada
como revisão estática, nunca como teste passado.
