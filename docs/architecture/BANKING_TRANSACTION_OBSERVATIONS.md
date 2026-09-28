# Observações normalizadas de transação

Status: **fundação persistente da Epic #63 / issue #111, estendida pelas #115 e #119**.

## Objetivo

Este recorte adiciona o primeiro armazenamento de dados financeiros vindos de uma
integração bancária sem transformar o provider em fonte de verdade do domínio.

O PostgreSQL local persiste uma camada de observações normalizadas com identidade
lógica suficiente para permitir sincronização idempotente e reconciliação local
posterior.

Ainda não existe criação automática de lançamento financeiro do usuário.

## Migration

Arquivo:

```text
0008_banking_transaction_observations.py
```

Revision ID:

```text
0008_banking_tx_observations
```

A revisão depende de `0007_banking_manual_sync` e mantém o identificador abaixo do
limite padrão de 32 caracteres da tabela `alembic_version`.

A migration cria:

```text
integrations.external_observations
```

A #115 não altera esse schema. A semântica de página terminal usa ausência da linha
em `sync_cursors`, portanto nenhuma migration adicional é necessária para o cursor.

A #119 adiciona uma candidate key local em `external_observations` para permitir FKs
de source residence-scoped da camada de reconciliação, sem mudar a semântica da
observação normalizada.

## Estrutura da observação

O primeiro `resource_type` suportado é exclusivamente:

```text
transactions
```

Campos persistidos:

```text
id local
residence_id
connection_id
external_account_id
resource_type
external_resource_id opcional
status
provider_updated_at opcional
effective_date
amount decimal
currency
description opcional
category opcional
stable_fingerprint
first_seen_at
last_seen_at
deleted_at opcional
normalized_payload_version
updated_at
```

O schema não contém request/response HTTP bruto, URL completa, headers, API key,
Connect Token, senha, MFA ou mensagem livre do provider.

## Estado observado

Estados permitidos:

```text
CONFIRMED
PENDING
INFERRED
DELETED
```

`DELETED` exige `deleted_at`. Os demais estados exigem `deleted_at IS NULL`.

`INFERRED` não pode declarar `external_resource_id`, pois sua identidade é derivada
do conteúdo normalizado.

Ausência de uma transação em uma página não produz deleção. Uma exclusão só é
persistida quando o snapshot normalizado declara explicitamente `DELETED`.

## Valores monetários

`amount` é recebido somente como `Decimal` e persistido em:

```text
NUMERIC(24,8)
```

O modelo rejeita:

- `float`;
- NaN/Infinity;
- mais de oito casas decimais;
- magnitude maior que a precisão do banco.

A validação ocorre antes de renderizar a forma decimal canônica, evitando que
expoentes extremos produzam material intermediário desnecessariamente grande.

A forma decimal canônica também participa do fingerprint quando não existe ID
estável do provider.

## Fingerprint estável

O fingerprint nunca é recebido pronto de uma API ou provider. Ele é calculado
internamente com SHA-256 usando namespace versionado:

```text
meufinanceiro:transaction-observation:v1
```

Quando há `external_resource_id`, a identidade da **observação** usa:

```text
namespace + external_account_id + external_resource_id
```

Quando não há ID externo, usa conteúdo normalizado:

```text
namespace
+ external_account_id
+ effective_date
+ amount decimal canônico
+ currency
+ description
+ category
```

O status não participa da identidade. Assim uma observação da mesma transação pode
mudar de `PENDING` para `CONFIRMED` sem necessariamente gerar outra linha.

O banco garante:

```text
UNIQUE(connection_id, external_account_id, stable_fingerprint)
```

e também unicidade parcial do ID externo não nulo na mesma conta.

A #119 mantém esse fingerprint como material interno da camada de observação. Na
camada canônica, `external_resource_id` é a autoridade quando existe; o fingerprint é
fallback apenas para observações sem ID. Identidades diferentes não são unidas por
fuzzy matching ou por semelhança de valores financeiros.

## RLS e vínculo com a conta

`external_observations` usa:

```text
ENABLE ROW LEVEL SECURITY
FORCE ROW LEVEL SECURITY
```

A política usa diretamente `app.current_residence_id`.

A FK composta:

```text
(connection_id, residence_id, external_account_id)
  -> integrations.external_accounts(
       connection_id,
       residence_id,
       external_account_id
     )
```

usa `ON DELETE RESTRICT`, impedindo que uma observação seja ligada a outra
conexão/residência e evitando cascade destrutivo do histórico observado.

## Commit atômico da página

`BankingIntegrationStore` expõe:

```text
apply_transaction_page(...)
```

A partir da #115, o parâmetro de checkpoint é:

```text
cursor: str | None
```

A operação executa uma única transação PostgreSQL:

```text
set installation/residence context
  -> resolve conexão
  -> lock da external_account
  -> preflight do cursor
  -> validar/aplicar observações
  -> confirmar ou remover checkpoint transactions
  -> COMMIT
```

O lock da conta serializa páginas/cursor da mesma conta dentro desta fronteira,
inclusive quando ainda não existe uma linha de cursor para bloquear.

Para página não terminal, o cursor é consultado antes de qualquer escrita. Se o mesmo
`committed_at`, cursor e `source_window` já estiverem confirmados, a página é tratada
como replay concluído e o payload recebido novamente não é reaplicado. Isso impede
que um cursor já confirmado seja reutilizado para anexar observações diferentes.

Uma observação não pode ter `observed_at` posterior ao `committed_at` da página.
Uma observação mais antiga não sobrescreve `status`, amount ou metadados de uma
observação mais recente. `first_seen_at` permanece o valor original e
`last_seen_at` só avança estritamente; replay exato não regrava a linha.

Se qualquer insert/update/constraint ou a mutação do checkpoint falhar, a transação é
revertida e nenhuma parte da página é confirmada.

Violações de unicidade são classificadas como conflito de identidade. Outras
falhas de integridade do banco são reduzidas a erro de persistência sanitizado,
sem ecoar valores financeiros ou parâmetros SQL.

## Página vazia

Uma página vazia pode confirmar um cursor novo explicitamente. Isso representa uma
consulta bem-sucedida do provider que não devolveu registros no intervalo, e não uma
inferência de exclusão.

Uma página vazia terminal (`cursor=None`) também pode encerrar um full-scan e remover
um recovery cursor anterior na mesma transação.

## Cursor e página terminal

O cursor continua opaco. Para página não terminal, a operação preserva as invariantes
da #109:

- commit anterior ao cursor atual falha;
- mesmo `committed_at` com cursor/window iguais é idempotente;
- mesmo instante com material diferente falha fechado;
- atualização posterior substitui o cursor confirmado;
- cursor/source window não entram no resultado do método.

Para a primeira estratégia de sincronização manual da #115, o cursor é um checkpoint
de **retomada de full-scan incompleto**, não um marcador incremental permanente.

Quando `cursor=None` em uma página terminal:

- as observações são aplicadas normalmente;
- eventual `sync_cursor` anterior é removido na mesma transação;
- a remoção só ocorre se o `committed_at` terminal for posterior ao checkpoint atual;
- falha da página preserva o checkpoint anterior por rollback;
- ausência da linha passa a significar que não há full-scan interrompido para retomar.

A coluna `sync_cursors.cursor` permanece `NOT NULL`; não se persiste `NULL` como
checkpoint.

A API histórica `commit_sync_cursor` criada na #109 continua disponível para outras
fronteiras internas, mas a orquestração de transações usa `apply_transaction_page`
para garantir atomicidade entre página e checkpoint.

## Resultado público do store

O método retorna somente:

```text
records_seen
records_applied
committed_at
```

Não retorna cursor, fingerprint, external account ID, external transaction ID,
amount ou descrição.

Os `repr` dos snapshots/records também omitem material financeiro e identificadores
externos.

## Relação com a orquestração e reconciliação

A #115 compõe esta fundação no orquestrador manual provider-neutral:

```text
sync_run
  -> executor contextual
  -> list_accounts
  -> replace_external_accounts
  -> list_transactions por conta/página
  -> apply_transaction_page
  -> finish_sync
```

A #119 adiciona uma fronteira local separada:

```text
external_observations
  -> reconcile_transaction_observations
  -> reconciled_transactions
```

A reconciliação materializa `PENDING`, `CONFIRMED`, `INFERRED` e `DELETED` em
identidades canônicas locais, mas permanece desacoplada do final de
`ManualBankingSyncService.run` neste estágio. Ela também não cria ou altera
lançamentos financeiros do domínio.

As observações continuam sendo o histórico normalizado da integração; o estado
canônico é uma projeção local derivada e reproduzível, não uma substituição do
histórico observado.

## Fora do escopo

- provider I/O dentro deste store;
- chamada Pluggy direta pelo store;
- geração de lançamentos financeiros;
- fuzzy matching/merge heurístico entre identidades distintas;
- endpoint HTTP e Flutter de sync/reconciliação;
- worker/polling;
- cartões, faturas e parcelas;
- desconexão/consentimento;
- webhooks;
- alteração de flags;
- deploy, HML ou produção.
