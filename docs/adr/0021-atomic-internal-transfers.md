# ADR-0021 — Transferências internas atômicas no ledger canônico

- Status: Accepted
- Data: 2026-08-13
- Decisores: mantenedores

## Contexto

ADR-0019 define que uma transferência não é um único `Movement`. Cada conta precisa receber um efeito local simples, portanto uma transferência interna coordena dois Movements `NEUTRAL`: débito na origem e crédito no destino.

A persistence append-only da #141 / ADR-0020 já garante idempotência, RLS, opening anchor e reversão integral para um Movement isolado, mas `FinancialMovementStore.create_movement()` controla a própria transação. Executar duas chamadas separadas não oferece atomicidade para uma operação que exige duas pernas inseparáveis.

Também existe um segundo risco: depois que duas pernas passam a representar uma única transferência, reverter apenas uma delas preservaria `result_effect=NEUTRAL`, porém quebraria a coerência patrimonial entre as duas contas.

## Decisão

### Transferência é uma operação sobre o mesmo ledger

A transferência não cria outro ledger e não mantém saldo próprio.

Ela persiste exatamente dois efeitos no ledger canônico:

```text
origem  -> Movement STANDARD / NEUTRAL / amount negativo
destino -> Movement STANDARD / NEUTRAL / amount positivo
```

Os amounts possuem mesma moeda e magnitude oposta. A soma das duas pernas é zero na moeda da transferência.

`finance.transfers` registra somente identidade, endpoints, vínculo entre as pernas, idempotência e auditoria técnica. A tabela não persiste `amount` autoritativo.

### Primeiro escopo: mesma moeda e mesmo owner

A primeira implementação aceita somente duas contas distintas:

- da mesma instalação;
- da mesma residência;
- da mesma moeda;
- `ACTIVE`;
- pertencentes ao operador corrente.

Cross-currency é rejeitado. Câmbio exige contrato próprio porque duas moedas não admitem a invariância simples de amounts opostos.

Audiência e capacidade de mutação permanecem conceitos distintos. Ler uma das contas não autoriza mover recursos entre ambas.

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

O domínio traduz a magnitude positiva para dois `FinancialMovementDraft` `NEUTRAL` com sinais opostos.

O cliente não escolhe `transfer_id`, `movement_id`, IDs internos das pernas, residência efetiva, installation ou operador efetivo.

### Identidades separadas

Conforme ADR-0017, os seguintes IDs permanecem semanticamente diferentes:

```text
transfer_id
source_movement_id
destination_movement_id
transfer idempotency key
movement-leg idempotency keys
reversal transfer id
```

O `transfer_id` usa UUID v4 local, opaco e server-side.

### Claim idempotente antes das pernas

Cada operação de transferência recebe uma `idempotency_key` UUID v4 e persiste `request_digest` SHA-256 de material canônico versionado.

Semântica:

```text
mesma key + mesmo digest     -> replay da mesma transferência
mesma key + digest diferente -> conflito fail-closed
```

A row de `finance.transfers` funciona como claim idempotente dentro da própria transação PostgreSQL.

Fluxo de criação:

1. derivar contexto e validar a intenção;
2. gerar `transfer_id`, IDs das duas pernas e idempotency keys internas das pernas;
3. inserir a row de transferência com `ON CONFLICT DO NOTHING` sobre `(installation_id, idempotency_key)`;
4. somente quem vence o claim insere as duas pernas;
5. commit valida as referências e a integridade das pernas;
6. qualquer falha faz rollback da transferência e de ambas as pernas.

As FKs da transferência para os Movements podem ser `DEFERRABLE INITIALLY DEFERRED`, permitindo que a row de claim referencie IDs gerados para linhas inseridas logo depois na mesma transação.

Isso evita estado `PENDING`, row mutável de preparação e advisory lock. Retries concorrentes convergem pela própria unique de idempotência.

### Transfer row append-only

A primeira estrutura persistida contém conceitualmente:

```text
id
installation_id
residence_id
source_account_id
destination_account_id
currency
source_movement_id
destination_movement_id
role STANDARD | REVERSAL
reversal_of_id nullable
created_by_operator_id
idempotency_key
request_digest
created_at
```

Não há `amount`, saldo ou status mutável.

Runtime recebe somente `SELECT, INSERT`. Não recebe `UPDATE` ou `DELETE`.

### Integridade entre transfer e Movement

A persistência deve provar em banco que uma transferência `STANDARD` referencia exatamente:

- source Movement `STANDARD/NEUTRAL` negativo;
- destination Movement `STANDARD/NEUTRAL` positivo;
- mesma magnitude absoluta;
- mesma moeda;
- mesma instalação e residência;
- source/destination accounts correspondentes aos endpoints da transferência;
- mesmas `effective_date` e `competence_date`;
- mesmo creator da transferência.

Uma perna não pode ser reutilizada por outra transferência.

As duas contas precisam respeitar individualmente seus opening anchors. Falha em qualquer perna aborta toda a transação.

### Audiência da transferência é a interseção

A row de transferência pode revelar a identidade de duas contas. Portanto, sua leitura exige que o ator esteja na audiência de **ambas** as contas.

Se um membro consegue ler apenas uma conta, ele pode continuar vendo o Movement `NEUTRAL` daquela conta conforme a RLS do ledger, mas não recebe o vínculo de transferência nem a identidade da outra conta por `finance.transfers`.

### Reversão pertence à transferência inteira

Uma perna vinculada a transferência não pode ser revertida pelo fluxo genérico `reverse_movement()`.

A correção usa `reverse_transfer(...)` com:

```text
transfer_id original
effective_date
competence_date
reason
```

A reversão cria atomicamente duas pernas `REVERSAL`:

```text
conta destino original -> amount negativo
conta origem original  -> amount positivo
```

Cada nova perna referencia a perna original correspondente e deriva amount, conta, moeda e `result_effect` conforme ADR-0020.

A transferência reversa possui `role=REVERSAL` e `reversal_of_id` apontando para a transferência original. Existe no máximo uma reversão integral por transferência original.

A proteção precisa existir também no banco: uma reversão de Movement cujo target pertença a transferência só é válida quando a mesma transação contém uma transferência reversa coerente referenciando a nova perna.

### Refatoração connection-scoped

Para preservar uma única implementação das invariantes de Movement, a persistence pode extrair primitives internas que operem sobre uma `Connection` já aberta.

A API pública atual de `FinancialMovementStore` permanece compatível e continua abrindo sua própria transação para operações isoladas.

`FinancialTransferStore` reutiliza as primitives internas dentro de uma única transação externa, sem duplicar regras de moeda, owner, opening anchor, idempotência de perna ou construção de record.

## Alternativas consideradas

### Duas chamadas públicas a `create_movement()`

Rejeitada. Cada chamada possui transação independente e pode persistir somente metade da transferência.

### Transferência como um único Movement com duas contas

Rejeitada pelo ADR-0019. Um Movement é efeito em exatamente uma conta.

### Persistir amount também em `finance.transfers`

Rejeitada por criar segunda autoridade monetária que poderia divergir das pernas do ledger.

### Advisory lock para serializar idempotência

Desnecessário no desenho preferido. A row append-only de transferência pode ser o próprio claim idempotente e a unique natural fornece serialização de concorrência.

### Permitir reversão isolada de uma perna

Rejeitada. Mantém neutralidade econômica, mas quebra a operação patrimonial composta e permite saldos incoerentes entre origem e destino.

### Cross-currency no primeiro recorte

Adiado. Exige taxa, arredondamento, moeda de referência e tratamento explícito da diferença entre os dois amounts.

## Consequências positivas

- zero risco de transferência parcialmente commitada;
- sem segundo ledger ou saldo paralelo;
- retries concorrentes convergem por contrato persistente;
- receita/despesa não é contaminada por movimentação interna;
- correções permanecem append-only e auditáveis;
- vínculo de transferência não vaza conta invisível;
- invariantes existentes de Movement continuam sendo reutilizadas.

## Consequências negativas e riscos

- migration precisa de constraints/triggers deferred mais sofisticados;
- reversão genérica de Movement passa a precisar reconhecer pernas vinculadas;
- store de Movement precisa de pequena refatoração interna connection-scoped;
- RLS da transferência consulta duas contas;
- testes de concorrência e rollback tornam-se obrigatórios antes de integração.

## Validação

A implementação deve cobrir, no mínimo:

- duas pernas `NEUTRAL` opostas e de mesma moeda;
- atomicidade sob falha depois da primeira perna;
- replay e conflito de idempotência;
- concorrência do mesmo request;
- owner/membership/status/RLS em ambas as contas;
- opening anchor em cada endpoint;
- interseção de audiência na leitura;
- bloqueio de reversão isolada;
- reversão atômica das duas pernas;
- ausência de `amount` e de `UPDATE/DELETE` em `finance.transfers`;
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
