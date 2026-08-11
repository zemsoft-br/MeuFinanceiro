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
- magnitude deve caber no contrato futuro `NUMERIC(24,8)`;
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

Todo recurso financeiro futuro deve possuir residência, proprietário e um escopo de visibilidade:

```text
PERSONAL  -> somente proprietário
SHARED    -> proprietário + grants explícitos
HOUSEHOLD -> qualquer membership ativa da residência
```

O contrato puro usa:

```python
from meufinanceiro_finance import (
    FinancialActorContext,
    FinancialResourceAudience,
    FinancialVisibilityScope,
    can_access_financial_resource,
)
```

A função de audiência não recebe papel administrativo. `owner` ou `administrator` da residência não é bypass para conteúdo `PERSONAL` de outro operador.

Membership inativa ou residência divergente sempre falham fechado. Grants são válidos somente em `SHARED` e não substituem membership ativa.

A capacidade de executar uma mutação continua separada da audiência. Casos de uso futuros combinam a audiência com a autorização por papel da membership.

O ADR-0016 exige que persistência financeira futura use RLS com `app.current_residence_id` e `app.current_operator_id` como defesa em profundidade.

Conversão cambial, regras de moeda específica, persistência de grants, saldo de abertura, contas e movimentações permanecem fora deste pacote inicial.
