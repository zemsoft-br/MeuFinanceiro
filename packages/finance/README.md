# meufinanceiro-finance

Contratos canônicos e provider-neutral do núcleo financeiro do MeuFinanceiro.

## Money

`Money` representa um valor monetário sem converter ou arredondar silenciosamente. `amount` deve ser `Decimal` finito; `float` não é aceito; moeda é ASCII uppercase de três letras; até oito casas decimais são preservadas; soma/subtração/comparação exigem a mesma moeda; serialização pública usa string decimal canônica.

Arredondamento não possui default implícito e exige escala + `RoundingMode` explícitos.

## Audiência de recursos financeiros

```text
PERSONAL  -> somente proprietário
SHARED    -> proprietário + grants explícitos
HOUSEHOLD -> qualquer membership ativa da residência
```

Papel administrativo da residência não é bypass para conteúdo `PERSONAL`. O ADR-0016 exige RLS com `app.current_residence_id` e `app.current_operator_id`.

## Identificadores canônicos

Recursos financeiros locais usam UUID v4 RFC 4122 opaco, gerado server-side. Strings não são convertidas implicitamente. IDs externos, FITID, hashes e fingerprints permanecem identidades de fonte e não substituem o UUID local.

## Contas financeiras

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

A conta possui moeda, owner e audiência, mas não possui amount ou saldo. A persistência da #133 aplica RLS e grants persistentes somente para contas `SHARED`.

## Categorias financeiras

A #135 adiciona a taxonomia financeira mínima como árvore de profundidade livre:

```python
from meufinanceiro_finance import (
    FinancialCategoryDraft,
    FinancialVisibilityScope,
)

category = FinancialCategoryDraft(
    name="Alimentação",
    visibility_scope=FinancialVisibilityScope.HOUSEHOLD,
)
```

Cada categoria possui UUID local, owner, audiência e `parent_id` opcional. Parent e child precisam compartilhar instalação, residência, owner e visibilidade.

Escopos suportados neste primeiro recorte:

```text
PERSONAL
HOUSEHOLD
```

`SHARED` é deliberadamente rejeitado até existir uma regra explícita de herança de grants em árvores. Isso evita filho mais visível que o pai ou caminhos parcialmente inacessíveis.

Estados estruturais:

```text
ACTIVE
DISABLED
```

O primeiro runtime cria somente `ACTIVE` e não possui update/move/disable/delete. Categoria não possui `income/expense kind`, amount, regra de provider ou vínculo com Movement neste estágio.

Saldo de abertura, Movement, tags, regras de categorização, aprendizado, carga inicial e UI permanecem fora dos contratos atuais.
