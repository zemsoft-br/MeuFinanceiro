# Observações normalizadas de transação

Status: **fundação persistente da Epic #63 / issue #111**.

## Objetivo

Este recorte adiciona o primeiro armazenamento de dados financeiros vindos de uma
integração bancária sem transformar o provider em fonte de verdade do domínio.

O PostgreSQL local persiste uma camada de observações normalizadas e imutáveis em
identidade lógica suficiente para permitir sincronização idempotente e futura
reconciliação.

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

A forma decimal canônica também participa do fingerprint quando não existe ID
estável do provider.

## Fingerprint estável

O fingerprint nunca é recebido pronto de uma API ou provider. Ele é calculado
internamente com SHA-256 usando namespace versionado:

```text
meufinanceiro:transaction-observation:v1
```

Quando há `external_resource_id`, a identidade usa:

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

A reconciliação de identidades distintas ainda é outro recorte.

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

A operação executa uma única transação PostgreSQL:

```text
set installation/residence context
  -> resolve conexão
  -> lock da external_account
  -> validar página/fingerprints
  -> upsert de cada observação
  -> confirmar cursor transactions
  -> COMMIT
```

O lock da conta serializa páginas/cursor da mesma conta, inclusive quando ainda não
existe uma linha de cursor para bloquear.

Uma observação mais antiga não sobrescreve `status`, amount ou metadados de uma
observação mais recente. `first_seen_at` permanece o valor original e
`last_seen_at` só avança.

Somente depois de aplicar a página a operação atualiza `sync_cursors`.

Se qualquer insert/update/constraint ou o commit do cursor falhar, o contexto da
transação é revertido e nenhuma parte da página é confirmada.

## Página vazia

Uma página vazia pode confirmar um cursor novo explicitamente. Isso representa uma
consulta bem-sucedida do provider que não devolveu registros no intervalo, e não uma
inferência de exclusão.

## Cursor

O cursor continua opaco. A operação de página preserva as invariantes da #109:

- commit anterior ao cursor atual falha;
- mesmo `committed_at` com cursor/window iguais é idempotente;
- mesmo instante com material diferente falha fechado;
- atualização posterior substitui o cursor confirmado;
- cursor/source window não entram no resultado do método.

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

## Relação com a próxima etapa

A partir desta fundação, o próximo recorte pode criar o orquestrador manual
provider-neutral:

```text
sync_run
  -> executor contextual
  -> list_accounts
  -> replace_external_accounts
  -> list_transactions por conta/página
  -> apply_transaction_page
  -> finish_sync
```

Esse orquestrador continuará sem reconciliar automaticamente as observações com
lançamentos do domínio. A reconciliação `PENDING`/`CONFIRMED`/`DELETED` será
estabilizada depois da primeira sincronização manual reproduzível.

## Fora do escopo

- provider I/O neste store;
- chamada Pluggy real;
- orquestrador/manual refresh;
- geração de lançamentos financeiros;
- reconciliação entre identidades diferentes;
- endpoint HTTP e Flutter de sync;
- worker/polling;
- cartões, faturas e parcelas;
- desconexão/consentimento;
- webhooks;
- alteração de flags;
- deploy, HML ou produção.
