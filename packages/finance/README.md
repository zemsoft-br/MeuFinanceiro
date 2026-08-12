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

Recursos financeiros possuem audiência derivável pela residência, proprietário e escopo de visibilidade da entidade que governa o acesso:

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

A capacidade de executar uma mutação continua separada da audiência. Casos de uso combinam a audiência com autorização por papel quando essa matriz estiver definida.

ADR-0016 exige RLS com `app.current_residence_id` e `app.current_operator_id` como defesa em profundidade. Opening balance e Movement herdam a audiência da conta em vez de duplicar ACL.

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

O contrato não converte strings implicitamente e rejeita UUID nil, versões diferentes de v4 e variants fora de RFC 4122.

O ID local não contém residência, proprietário, tipo, timestamp, valor, moeda ou material de provider. IDs de provider/importador, FITID, hashes e fingerprints continuam sendo identidades de fonte e nunca substituem o UUID canônico do recurso.

Idempotency key, correlation ID, reconciliation ID e transfer ID são conceitos independentes.

Operações persistentes de Movement usam uma chave própria:

```python
from meufinanceiro_finance import new_financial_idempotency_key

idempotency_key = new_financial_idempotency_key()
```

Ela também é UUID v4, mas é identidade operacional de retry e nunca o `movement_id`.

ADR-0017 mantém geração canônica server-side. Client-generated IDs para eventual modo offline exigem decisão própria de idempotência e conflitos.

## Contas financeiras

A entidade financeira canônica usa contratos provider-neutral:

```python
from meufinanceiro_finance import (
    FinancialAccountDraft,
    FinancialAccountStatus,
    FinancialAccountType,
    FinancialVisibilityScope,
)

account = FinancialAccountDraft(
    name="Conta principal",
    currency="BRL",
    account_type=FinancialAccountType.CHECKING,
    visibility_scope=FinancialVisibilityScope.PERSONAL,
)
```

Tipos iniciais:

```text
CHECKING
SAVINGS
CASH
DIGITAL_WALLET
INVESTMENT
BENEFIT
CUSTOM
```

`CUSTOM` exige nome de tipo explícito. Os demais tipos não aceitam esse campo.

A conta possui moeda, mas **não possui amount ou saldo**. A persistência da #133 aplica audiência e IDs diretamente no PostgreSQL; grants persistentes existem somente para contas `SHARED`.

O estado persistente prevê `ACTIVE` e `ARCHIVED`, porém arquivamento continua exigindo caso de uso, capacidade por papel e auditoria próprios.

## Categorias-base

A #135 adiciona categorias provider-neutral em árvore, separadas da conta e do ledger. O vínculo classificatório de Movement permanece fronteira própria para que audiência e redaction sejam resolvidas sem copiar eventos financeiros.

## Saldo de abertura

ADR-0018 / #137 define zero ou um anchor imutável por conta:

```python
from datetime import date
from decimal import Decimal

from meufinanceiro_finance import FinancialOpeningBalanceDraft, Money

opening = FinancialOpeningBalanceDraft(
    amount=Money(Decimal("1000.00"), "BRL"),
    effective_date=date(2026, 8, 1),
)
```

Ausência de row é diferente de saldo explicitamente zero. O anchor representa o saldo no início de `effective_date` e não é saldo atual nem cache.

## Movement

ADR-0019 define Movement como efeito monetário efetivo em exatamente uma conta:

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

O draft original informa conta, `Money`, resultado econômico, `effective_date`, `competence_date` e descrição. Reversão recebe apenas original, datas e reason; amount/conta/moeda/result effect são derivados da linha original.

A #141 / ADR-0020 materializa a persistence append-only:

- `finance.movements`;
- runtime com `SELECT, INSERT`, sem `UPDATE/DELETE`;
- replay idempotente por key + digest canônico;
- reversão integral única como novo evento;
- row lock serializando reversões concorrentes;
- RLS herdando a audiência da conta;
- bloqueio de novo Movement anterior ao opening anchor existente.

O record persistido e erros genéricos redigem material financeiro sensível.

## Ainda fora deste pacote base

- cálculo/materialização de saldo;
- transferências atômicas;
- rateios e vínculo classificatório de Movement;
- matriz completa de capacidade por papel;
- conversão cambial;
- API/FastAPI;
- Flutter;
- Pluggy/importadores;
- cartões/faturas;
- empréstimos.
