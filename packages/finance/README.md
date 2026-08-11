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

Conversão cambial, regras de moeda específica, saldo de abertura, contas e movimentações permanecem fora deste pacote inicial.
