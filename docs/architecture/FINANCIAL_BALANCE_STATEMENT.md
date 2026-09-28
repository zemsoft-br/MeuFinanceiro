# Saldo e extrato derivados do ledger

- Issue: #174
- Estado: contrato inicial provider-neutral
- Autoridade monetária: opening balance imutável + `Movement.amount`

## Fórmula

```text
base = opening balance quando informado; caso contrário zero como identidade aditiva
movement_net = soma de todos os Movement.amount da conta
current_balance = base + movement_net
```

A ausência de opening balance permanece explícita como `None`. Zero matemático não significa que o usuário informou saldo inicial zero.

## Extrato

O extrato contém somente Movements reais, ordenados por:

```text
effective_date ASC
created_at ASC
movement_id ASC
```

Cada entrada carrega o Movement e o saldo derivado imediatamente após ele. O opening balance é provenance/cabeçalho e nunca vira Movement sintético.

STANDARD e REVERSAL permanecem visíveis separadamente. Ambos participam da soma pelo amount assinado. `result_effect` não substitui o sinal monetário no cálculo de caixa.

## Segurança e consistência

A query service lê primeiro a conta visível e depois reutiliza as stores RLS-aware de opening balance e Movements. Nenhuma autorização é reimplementada no agregador.

Inconsistências de `account_id` ou moeda falham fechado. Erros de persistence não são convertidos para zero.

## Proibições

Não introduzir nesta camada:

- coluna `balance` mutável;
- materialized view/cache autoritativo;
- float;
- arredondamento implícito;
- conversão cambial;
- provider/Pluggy;
- nova tabela/migration;
- mutação de ledger.

## Exposição no Alpha

A #191 expõe snapshot e extrato pela API autenticada:

```text
GET /finance/accounts/{account_id}/balance
GET /finance/accounts/{account_id}/statement
```

A API apenas serializa `FinancialBalanceQueryService`; não materializa saldo nem reimplementa a soma. A UI Flutter permanece em recorte posterior.

Paginação/range temporal exige contrato próprio para preservar o running balance correto da página.