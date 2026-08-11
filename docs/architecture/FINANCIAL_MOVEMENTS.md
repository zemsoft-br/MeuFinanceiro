# Movement canônico e ledger append-only

Status: **contrato de domínio da Fase 1 / issue #139**.

Normativo: ADR-0019.

## Unidade do ledger

Um Movement é um efeito monetário efetivo em uma única conta financeira canônica.

```text
amount > 0 -> aumenta saldo
amount < 0 -> reduz saldo
amount = 0 -> inválido
```

Não existe campo redundante `credit/debit`.

O Movement não é projeção, recorrência futura, observação bancária, fatura, orçamento ou saldo.

## Resultado econômico

```text
INCOME
EXPENSE
NEUTRAL
```

Para eventos originais:

```text
INCOME  -> amount positivo
EXPENSE -> amount negativo
NEUTRAL -> positivo ou negativo, nunca zero
```

`NEUTRAL` permite representar futuramente efeitos patrimoniais sem tratá-los como receita/despesa.

## Datas

Todo evento original possui:

```text
effective_date
competence_date
```

A primeira participa de caixa/saldo; a segunda de competência. Ambas são `date` e não possuem default implícito entre si.

## Audiência

Movement herda integralmente a audiência da conta. Não possui owner, visibility scope ou grants independentes.

A futura persistência deverá consultar a conta sob RLS para leitura/escrita, sem copiar ACL.

## Categoria

O contrato base não contém `category_id`. O vínculo classificatório será uma etapa posterior porque contas `SHARED` e categorias atualmente possuem modelos de audiência diferentes.

## Imutabilidade

Movements persistidos serão append-only. Não haverá edição destrutiva de conta, amount, datas, resultado ou descrição.

Não existe `PENDING` no ledger canônico. Pending permanece em projeções/observações externas.

## Reversão

O comando de reversão recebe somente:

```text
movement_id
effective_date
competence_date
reason
```

Amount, conta, moeda e resultado serão derivados do original pela futura camada de persistence/service.

A reversão integral terá amount oposto, mesma conta, moeda e result effect. Não será permitido reverter uma reversão ou criar mais de uma reversão integral para o mesmo original.

## Transferência futura

Transferência será uma operação atômica externa ao Movement básico:

```text
origem  -> NEUTRAL negativo
destino -> NEUTRAL positivo
```

Os dois eventos serão ligados por um `transfer_id` distinto dos `movement_id`.

## Idempotência

A futura criação persistente exigirá idempotency key independente do UUID canônico do Movement. Formato, escopo e retenção serão decididos na issue de persistence do ledger.

## Saldo

Após existir persistence de Movements, o saldo poderá ser derivado de:

```text
opening balance + soma dos Movement.amount efetivos
```

Nenhum saldo materializado é introduzido pelo contrato #139.

## Fora do escopo

- schema/store de Movement;
- category link;
- transferências;
- rateios;
- partial refund/correction;
- saldo materializado;
- API/Flutter;
- Pluggy/importadores;
- deploy/HML/produção.
