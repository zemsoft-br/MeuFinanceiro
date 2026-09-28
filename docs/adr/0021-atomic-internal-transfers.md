# ADR-0021 — Transferências internas atômicas no ledger canônico

- Status: Accepted
- Data: 2026-08-13
- Decisores: mantenedores

## Contexto

ADR-0019 define que uma transferência não é um único `Movement`. Cada conta recebe um efeito local simples; portanto uma transferência interna coordena dois Movements `NEUTRAL`, débito na origem e crédito no destino.

A persistence da #141 / ADR-0020 garante idempotência, RLS, opening anchor e reversão integral para um Movement isolado, mas `FinancialMovementStore.create_movement()` controla a própria transação. Duas chamadas públicas separadas não formam uma transferência atômica.

Depois que duas pernas representam uma única operação, reverter apenas uma delas também é inválido: a neutralidade econômica seria preservada, mas os saldos patrimoniais das contas ficariam incoerentes.

## Decisão

### Transferência usa o mesmo ledger

A transferência persiste exatamente dois efeitos no ledger canônico:

```text
origem  -> Movement STANDARD / NEUTRAL / amount negativo
destino -> Movement STANDARD / NEUTRAL / amount positivo
```

Os amounts possuem a mesma moeda e magnitude oposta. Sua soma é zero.

Não existe segundo ledger, saldo próprio ou amount autoritativo fora de `finance.movements`.

### Primeiro escopo

A primeira implementação aceita duas contas distintas:

- da mesma instalação;
- da mesma residência;
- da mesma moeda;
- `ACTIVE`;
- pertencentes ao operador corrente.

Cross-currency é fail-closed e exige contrato próprio de câmbio.

### Contrato do domínio

A intenção de criação informa:

```text
source_account_id
destination_account_id
magnitude Money positiva
effective_date
competence_date
description
```

O domínio produz dois `FinancialMovementDraft` `NEUTRAL` com sinais opostos. O cliente não escolhe `transfer_id`, `movement_id`, IDs internos das pernas, residência, installation ou operador efetivos.

### Identidades separadas

Conforme ADR-0017:

```text
transfer_id
source_movement_id
destination_movement_id
transfer idempotency key
movement-leg idempotency keys
reversal transfer id
```

são conceitos distintos. O `transfer_id` é UUID v4 local, opaco e server-side.

### Persistência relacional normalizada

A operação append-only é persistida em:

```text
finance.transfers
```

com identidade, installation/residence, contas de origem/destino, moeda, role, reversão, creator, idempotência, digest e timestamp técnico.

A tabela **não possui amount**.

O vínculo das duas pernas é normalizado em:

```text
finance.transfer_legs
```

com:

```text
transfer_id
direction SOURCE | DESTINATION
movement_id
```

A chave primária `(transfer_id, direction)` garante exatamente uma posição por direção, e `UNIQUE(movement_id)` garante que um Movement pertença a no máximo uma transferência em qualquer direção. Isso fecha a reutilização cruzada que duas uniques independentes em colunas SOURCE/DESTINATION não conseguiriam impedir.

A FK `movement_id -> finance.movements(id)` é `DEFERRABLE INITIALLY DEFERRED`, permitindo registrar o vínculo com IDs server-side antes de inserir as pernas na mesma transação.

### Claim idempotente antes das pernas

Cada operação recebe `idempotency_key` UUID v4 e `request_digest` SHA-256 de material canônico versionado.

```text
mesma key + mesmo digest      -> replay da mesma transferência
mesma key + digest diferente  -> conflito fail-closed
```

Fluxo:

1. validar contexto e endpoints;
2. gerar `transfer_id`, dois `movement_id` e duas idempotency keys internas;
3. inserir `finance.transfers` com `ON CONFLICT DO NOTHING` em `(installation_id, idempotency_key)`;
4. somente quem vence o claim insere os dois registros de `transfer_legs`;
5. inserir os dois Movements;
6. constraints deferred validam a relação no commit;
7. qualquer falha faz rollback do claim, links e Movements.

Não existe estado `PENDING`, update posterior ou advisory lock de idempotência.

### Integridade deferred

Um constraint trigger deferred valida que uma transferência `STANDARD` possui:

- exatamente uma perna SOURCE e uma DESTINATION;
- SOURCE em `source_account_id` com amount negativo;
- DESTINATION em `destination_account_id` com amount positivo;
- ambas `STANDARD/NEUTRAL`;
- amounts exatamente opostos;
- mesma moeda;
- mesma installation/residence;
- mesmo creator;
- mesmas `effective_date` e `competence_date`;
- mesma descrição canônica.

Os opening anchors continuam sendo verificados por conta. Se qualquer perna falhar, nada é commitado.

### Audiência é a interseção

`finance.transfers` revela duas contas. Sua leitura exige que o ator pertença à audiência de **ambas**.

Um membro pode enxergar o Movement `NEUTRAL` de uma conta `HOUSEHOLD` e ainda assim não receber o vínculo da transferência se a outra conta for `PERSONAL` de outro operador.

`finance.transfer_legs` herda acesso da row pai e não abre uma rota lateral para descobrir movimentos ou contas invisíveis.

Runtime recebe apenas `SELECT, INSERT` em `transfers` e `transfer_legs`. Não recebe `UPDATE/DELETE`.

### Reversão é da transferência inteira

Uma perna de transferência não pode ser revertida pelo fluxo genérico isolado.

O comando próprio recebe:

```text
transfer_id original
effective_date
competence_date
reason
```

Para uma transferência original `A -> B`:

```text
original SOURCE      A -100
original DESTINATION B +100

reversal SOURCE      B -100  -> reverte original DESTINATION
reversal DESTINATION A +100  -> reverte original SOURCE
```

A transferência reversa possui `role=REVERSAL` e `reversal_of_id` para a original. Cada nova perna é um Movement `REVERSAL` conforme ADR-0020. Existe no máximo uma reversão integral por transferência original.

O trigger de reversão de Movement também consulta `transfer_legs`: se o target pertence a uma transferência, a inserção só é aceita quando a mesma transação já contém uma transferência reversa coerente e o novo Movement ocupa a direção oposta esperada.

### Reutilização das invariantes de Movement

A API pública de `FinancialMovementStore` permanece compatível.

`FinancialTransferStore` executa uma única transação e reutiliza helpers internos já existentes para:

- contexto RLS;
- membership ativa;
- ownership/status/moeda da conta;
- opening anchor;
- row lock de reversão;
- digest de request das pernas.

As pequenas primitives de insert de perna permanecem internas ao store de transferência por enquanto. Uma refatoração connection-scoped mais ampla só deve ser feita se a validação mostrar ganho claro sem reabrir os contratos da #141.

## Alternativas consideradas

### Duas chamadas a `create_movement()`

Rejeitada porque cada chamada controla sua própria transação.

### Transferência como um único Movement com duas contas

Rejeitada pelo ADR-0019. Movement é efeito em exatamente uma conta.

### Persistir amount em `finance.transfers`

Rejeitada por duplicar autoridade monetária.

### Duas colunas `source_movement_id` / `destination_movement_id` com uniques independentes

Rejeitada após revisão. Elas não impedem reutilizar o mesmo Movement como SOURCE de uma transferência e DESTINATION de outra. `finance.transfer_legs` com `UNIQUE(movement_id)` fecha essa brecha de forma declarativa e concorrente.

### Advisory lock para idempotência ou unicidade das pernas

Rejeitado. A unique do claim serializa retries e a relation normalizada possui unique global do `movement_id`.

### Reversão isolada de uma perna

Rejeitada porque quebra a operação patrimonial composta.

### Cross-currency agora

Adiado. Requer taxa, arredondamento e semântica explícita de diferença cambial.

## Consequências positivas

- transferência nunca é parcialmente commitada;
- nenhuma segunda autoridade de saldo/amount;
- retries concorrentes convergem pelo claim persistente;
- cada Movement pertence a no máximo uma transferência;
- transferências não contaminam receita/despesa;
- correções são append-only e atômicas;
- vínculo de transferência não vaza conta invisível.

## Consequências negativas e riscos

- adiciona uma relation table para as pernas;
- migration usa FKs e constraint trigger deferred;
- reversão genérica precisa reconhecer legs vinculadas;
- RLS precisa cobrir operação e relation;
- concorrência, rollback e downgrade exigem prova PostgreSQL antes do merge.

## Validação

Antes da integração devem ser provados:

- duas pernas `NEUTRAL` opostas;
- `UNIQUE(movement_id)` em `transfer_legs`;
- rollback total se a segunda perna falhar;
- replay/conflito e corrida da mesma idempotency key;
- owner/membership/status/moeda nas duas contas;
- opening anchor nos dois endpoints;
- audiência como interseção;
- bloqueio de reversão isolada;
- reversão atômica com orientação invertida;
- runtime sem `UPDATE/DELETE`;
- ausência de amount em `finance.transfers`;
- downgrade/reupgrade simétricos.

## Referências

- #124
- #169
- ADR-0015
- ADR-0016
- ADR-0017
- ADR-0018
- ADR-0019
- ADR-0020
- `docs/architecture/FINANCIAL_MOVEMENTS.md`
- `docs/architecture/FINANCIAL_INVARIANTS.md`
