# meufinanceiro-finance

Contratos canônicos e provider-neutral do núcleo financeiro do MeuFinanceiro.

## Money

`Money` representa um valor monetário sem converter ou arredondar silenciosamente:

```python
from decimal import Decimal

from meufinanceiro_finance import Money

amount = Money(Decimal("123.45"), "BRL")
```

Invariantes:

- `amount` deve ser `Decimal` finito;
- `float` não é aceito;
- moeda deve ser código ASCII uppercase de três letras;
- até oito casas decimais são preservadas;
- magnitude deve caber em `NUMERIC(24,8)`;
- soma, subtração e comparação ordenada exigem a mesma moeda;
- `repr` e `str` não exibem o valor financeiro;
- serialização pública usa string decimal canônica, nunca `float`.

## Arredondamento

Arredondamento não possui default implícito. O caso de uso informa escala e modo:

```python
from meufinanceiro_finance import Money, RoundingMode

rounded = amount.quantize(scale=2, rounding=RoundingMode.HALF_EVEN)
```

Os modos iniciais são `HALF_EVEN`, `HALF_UP` e `DOWN`.

## Audiência de recursos financeiros

A audiência financeira canônica usa residência, proprietário e escopo de visibilidade:

```text
PERSONAL  -> somente proprietário
SHARED    -> proprietário + grants explícitos
HOUSEHOLD -> qualquer membership ativa da residência
```

O contrato puro usa `FinancialActorContext`, `FinancialResourceAudience`, `FinancialVisibilityScope` e `can_access_financial_resource`.

Papel administrativo não concede bypass para conteúdo `PERSONAL` alheio. Membership inativa ou residência divergente falham fechado. Grants são válidos somente em `SHARED` e não substituem membership ativa.

A capacidade de mutação continua separada da audiência. ADR-0016 exige RLS com `app.current_residence_id` e `app.current_operator_id` como defesa em profundidade.

## Identificadores canônicos

Recursos financeiros locais usam UUID v4 RFC 4122 opaco:

```python
from meufinanceiro_finance import (
    new_financial_resource_id,
    validate_financial_resource_id,
)

resource_id = new_financial_resource_id()
validate_financial_resource_id(resource_id)
```

O ID local não codifica residência, proprietário, tipo, timestamp, valor, moeda ou provider. IDs externos, idempotency keys, correlation IDs, reconciliation IDs e transfer IDs são identidades distintas do resource ID.

## Contas financeiras

A #133 materializou contas provider-neutral com:

- UUID v4 local;
- `PERSONAL`, `SHARED` e `HOUSEHOLD`;
- tipos `CHECKING`, `SAVINGS`, `CASH`, `DIGITAL_WALLET`, `INVESTMENT`, `BENEFIT` e `CUSTOM`;
- moeda canônica;
- RLS e grants persistentes para `SHARED`;
- nenhuma coluna autoritativa de saldo.

A conta possui estado `ACTIVE`/`ARCHIVED`, mas lifecycle completo de arquivamento permanece caso de uso próprio.

## Categorias-base

A #135 define categorias financeiras provider-neutral em árvore:

```python
from meufinanceiro_finance import (
    FinancialCategoryDraft,
    FinancialCategoryRecord,
    FinancialCategoryStatus,
)
```

Categorias suportam `PERSONAL` e `HOUSEHOLD`, parent opcional da mesma árvore/audiência e lifecycle `ACTIVE`/`DISABLED`. `SHARED` foi deliberadamente adiado porque o vínculo classificatório com contas/Movements precisa resolver audiência sem duplicar ACL.

A persistência canônica fica em `finance.categories`, protegida por RLS e sem `UPDATE/DELETE` runtime neste primeiro recorte.

## Saldo de abertura

ADR-0018 / #137 define zero ou um saldo de abertura imutável por conta. O anchor representa o saldo no início de `effective_date` e é diferente de saldo atual, cache ou observação bancária.

Ausência de anchor é diferente de um anchor explicitamente zero. A moeda é vinculada à moeda da conta por FK composta e o runtime não possui caminho destrutivo de edição.

## Movement

ADR-0019 / #139 define Movement como efeito monetário efetivo em exatamente uma conta:

```text
amount > 0 -> aumenta saldo
amount < 0 -> reduz saldo
amount = 0 -> inválido
```

Resultado econômico é separado do sinal:

```text
INCOME
EXPENSE
NEUTRAL
```

O contrato possui `effective_date` e `competence_date` explícitas. Correções são novos eventos de reversão; o original não é editado.

A persistence append-only, idempotência operacional e serialização de reversões estão na #141 / PR #142 e permanecem **em validação, ainda não integradas em `develop`**.

## Estado desta reconciliação

A branch da #135 restaura a entrega de categorias-base que havia permanecido fora de `develop`, embora migrations posteriores já dependessem de `0012_financial_categories`.

Após essa dependência ser integrada e os quality gates de baseline serem reconciliados, a validação da persistence de Movement #141 pode prosseguir sobre uma cadeia Alembic linear e completa.

## Ainda fora deste pacote base

- cálculo/materialização de saldo;
- transferências atômicas;
- rateios e vínculo classificatório de Movement;
- matriz completa de capacidade por papel;
- conversão cambial;
- API/Flutter do núcleo financeiro;
- importadores como autoridade do ledger;
- cartões/faturas;
- empréstimos.
