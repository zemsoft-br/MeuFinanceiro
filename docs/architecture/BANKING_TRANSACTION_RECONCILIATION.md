# Reconciliação local de observações bancárias

Status: **implementação da Epic #63 / issue #119**.

## Objetivo

Este recorte transforma observações normalizadas de transações em um estado canônico
local e reproduzível, sem criar lançamento financeiro do usuário e sem executar I/O de
provider.

A fonte continua sendo:

```text
integrations.external_observations
```

A reconciliação materializa somente identidade e estado em:

```text
integrations.reconciled_transactions
integrations.reconciled_transaction_sources
```

## Identidade canônica

A identidade é conservadora e determinística.

Quando a observação possui `external_resource_id`:

```text
identity_kind = PROVIDER_ID
```

O digest local é SHA-256 de um namespace versionado mais:

```text
residence_id
connection_id
external_account_record_id
resource_type = transactions
identity_kind
external_resource_id
```

Quando não existe ID do provider:

```text
identity_kind = FINGERPRINT
```

O mesmo escopo é usado, substituindo o ID externo pelo `stable_fingerprint` já
calculado pela camada de observação.

Nenhum dos campos abaixo participa da identidade:

```text
amount
description
category
effective_date
status
```

Não existe fuzzy matching, proximidade temporal ou merge heurístico. Uma observação
inferida sem ID não é automaticamente unida a uma transação que depois apareça com ID
do provider.

## Estado canônico

`reconciled_transactions` mantém somente:

```text
UUID local
residence_id
connection_id
UUID local da external_account
identity_kind
identity_digest
status
UUID local da observação fonte
source_observed_at
first_reconciled_at
updated_at
```

Estados válidos:

```text
PENDING
CONFIRMED
INFERRED
DELETED
```

`DELETED` só é materializado quando a observação normalizada possui explicitamente
esse estado. Ausência em página, snapshot ou execução não significa deleção.

## Checkpoint local de reconciliação

`reconciled_transaction_sources` registra qual versão **local** de cada observação já
foi processada:

```text
source_observation_id
reconciled_transaction_id
observation_updated_at
first_reconciled_at
updated_at
```

Esse marcador não contém cursor do provider, payload financeiro nem identificador
externo. Ele serve para descobrir observações novas ou alteradas sem reprocessar toda
a tabela.

A seleção bounded considera suja uma observação quando:

```text
não existe source progress
ou
source.observation_updated_at != observation.updated_at
```

A ordem de consumo é:

```text
external_observations.updated_at
external_observations.id
```

Essa ordem é apenas o scheduler local do backlog. A decisão de qual estado canônico é
mais novo usa `last_seen_at`, persistido como `source_observed_at`.

## Regras temporais

Para a mesma identidade:

```text
source_observed_at novo > atual  -> atualiza estado canônico
source_observed_at novo < atual  -> não regride; marca fonte como observada
source_observed_at novo = atual  -> replay compatível ou conflito
```

No empate temporal, `source_observation_id` e `status` precisam ser compatíveis. Caso
contrário, a operação falha fechado com erro sanitizado; nenhuma ordem acidental de
SQL ou provider escolhe o vencedor.

## Bounded e atomicidade

Operação pública interna:

```text
reconcile_transaction_observations(
    installation_id,
    residence_id,
    connection_id,
    limit=500,
)
```

Limites:

```text
default = 500 observações
máximo = 1000 observações
```

A consulta lê no máximo `limit + 1` para produzir `has_more` sem expor cursor.

As observações selecionadas são bloqueadas com `FOR UPDATE`. O batch inteiro executa
em uma única transação PostgreSQL:

```text
set installation/residence context
  -> validar connection local
  -> selecionar observações dirty bounded
  -> calcular identidade sem material financeiro
  -> lock do estado canônico
  -> aplicar create/update/unchanged
  -> atualizar checkpoint local da observação
  -> COMMIT
```

Conflito de unicidade, empate incompatível ou mudança concorrente de estado provoca
rollback do batch. Não existe resultado parcialmente confirmado dentro de uma chamada.

## Resultado

`TransactionReconciliationResult` contém somente:

```text
observations_seen
identities_created
identities_updated
identities_unchanged
has_more
```

Não contém:

- external resource ID;
- fingerprint;
- identity digest;
- amount;
- descrição;
- categoria;
- cursor;
- credencial ou token.

Os `repr` dos contratos também redigem identidade e escopo.

## RLS e integridade

Migration:

```text
0010_banking_tx_reconciliation
```

Base:

```text
0009_banking_sync_fairness
```

As duas tabelas novas usam:

```text
ENABLE ROW LEVEL SECURITY
FORCE ROW LEVEL SECURITY
```

A policy usa `app.current_residence_id`.

A migration adiciona uma candidate key local a `external_observations` para que FKs
de source fechem residência e conexão no PostgreSQL. O estado canônico referencia a
conta por UUID local e FK composta com `connection_id` + `residence_id`.

## Integração com a sincronização

A #119 permanece deliberadamente desacoplada de `ManualBankingSyncService.run`.

A sincronização pode produzir/atualizar observações. A reconciliação é uma operação
local explícita e repetível sobre o backlog persistido. A composição automática entre
as duas fronteiras será decidida somente depois de validar replay, concorrência e UX
do fluxo manual.

## Fora do escopo

- criação ou edição de lançamento financeiro do usuário;
- fuzzy matching e merge heurístico;
- confirmação manual pelo usuário;
- endpoint FastAPI e Flutter;
- `changed_since` incremental do provider;
- worker/background sync;
- cartões, faturas e parcelas;
- investimentos e empréstimos;
- webhooks;
- chamada Pluggy real;
- alteração de feature flags;
- deploy, HML ou produção.

## Validação

Os testes adicionados são sintéticos e cobrem identidade, transições explícitas,
bounded processing, replay, conflito temporal e RLS.

GitHub Actions não é gate operacional desta etapa. Qualquer validação que não tenha
sido realmente executada nesta sessão deve permanecer declarada como não executada.
