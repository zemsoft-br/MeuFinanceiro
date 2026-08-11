# Saldo de abertura imutável

Status: **anchor inicial do livro financeiro / issue #137**.

## Objetivo

O saldo de abertura representa o estado financeiro conhecido no início da vida contábil de uma conta no MeuFinanceiro. Ele é separado da entidade `finance.accounts` e não representa saldo atual.

Contrato normativo: ADR-0018.

## Semântica

Cada conta possui zero ou um anchor.

```text
sem row            -> saldo de abertura não informado
row amount = 0     -> saldo de abertura explicitamente zero
```

Esses estados não são equivalentes.

`effective_date` representa o saldo no início do dia financeiro informado, antes dos futuros movimentos efetivos nessa data.

## Persistência

Tabela:

```text
finance.account_opening_balances
```

Campos:

```text
id
installation_id
residence_id
account_id
currency
amount
effective_date
created_by_operator_id
created_at
```

Não existem `updated_at`, versão mutável ou coluna equivalente em `finance.accounts`.

`amount` usa `NUMERIC(24,8)` e `currency` segue o contrato `Money`.

Uma unique constraint em `account_id` garante um único anchor.

## Vínculo com a conta

A migration adiciona a candidate key:

```text
finance.accounts(id, installation_id, residence_id, currency)
```

O opening balance referencia exatamente essa combinação. Isso impede persistir anchor em moeda diferente da conta ou cruzar residência/instalação.

## Criação

Neste recorte, somente o owner da conta pode criar o anchor.

Requisitos:

```text
membership ativa
mesma residência
conta visível
owner_operator_id = current operator
conta ACTIVE
currency igual à conta
```

O store gera UUID v4 local e não aceita ID do provider.

Segunda criação para a mesma conta falha com conflito sanitizado. Não há upsert.

## Audiência

A RLS do anchor não duplica `visibility_scope` nem grants.

Para SELECT, a policy exige uma linha correspondente em `finance.accounts` que seja visível ao ator atual sob a própria RLS da conta. Portanto:

```text
PERSONAL  -> somente owner
SHARED    -> owner + grants da conta
HOUSEHOLD -> memberships ativas
```

Um membro que pode ler uma conta pode ler seu anchor, mas apenas o owner pode criá-lo.

## Imutabilidade

Permissões runtime:

```text
SELECT
INSERT
```

Não existem:

```text
UPDATE
DELETE
UPSERT
```

Correções futuras devem ser eventos explícitos do livro. O anchor original não é reescrito.

## Relação com o saldo futuro

Conceitualmente:

```text
saldo derivado = opening balance + efeitos do ledger canônico
```

Essa fórmula ainda não é executada porque Movement não foi definido.

O anchor não é:

- saldo atual;
- cache de saldo;
- saldo observado pela Pluggy;
- ajuste;
- receita ou despesa;
- Movement.

## Fora do escopo

- cálculo de saldo atual;
- Movement/ledger;
- ajustes e reversões;
- edição do anchor;
- múltiplas versões;
- API/Flutter;
- saldos bancários observados;
- importação/Pluggy;
- deploy/HML/produção.

## Validação

Testes sintéticos foram escritos para ausência versus zero, moeda, owner-only create, audiência herdada, segunda criação, conta arquivada, RLS, permissões imutáveis e migration downgrade/reupgrade.

Nesta sessão, a validação disponível continua sendo revisão estática via GitHub; Ruff, mypy, pytest, PostgreSQL integration e Quality integral não são declarados como executados.
