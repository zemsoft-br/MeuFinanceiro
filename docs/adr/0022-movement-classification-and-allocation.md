# ADR-0022 — Classificação e rateio append-only de Movements

- Status: Accepted
- Data: 2026-08-13
- Decisores: mantenedores

## Contexto

O ledger canônico já representa cada efeito financeiro efetivo como `Movement` append-only. O `Movement.amount` é a autoridade monetária para saldo e resultado econômico, enquanto categorias são uma dimensão analítica independente.

O ADR-0019 deixou `category_id` fora do primeiro Movement porque uma classificação simples embutida no ledger teria três problemas: não suportaria rateio múltiplo, misturaria classificação com autoridade de saldo e poderia criar incompatibilidade de audiência entre a conta e a categoria.

Contas aceitam visibilidade `PERSONAL`, `SHARED` e `HOUSEHOLD`. Categorias atuais aceitam apenas `PERSONAL` e `HOUSEHOLD`. Portanto, uma classificação precisa ser uma fronteira própria e precisa impedir que um vínculo visível revele uma categoria mais privada que o Movement classificado.

## Decisão

### Rateio não é ledger

Classificação e rateio não criam novo efeito financeiro.

O saldo e o resultado econômico continuam derivados exclusivamente do ledger:

```text
opening balance + soma de Movement.amount
```

As parcelas de rateio existem apenas para análise, relatórios e UX. Nenhuma soma de allocations participa do cálculo de saldo.

`finance.movements` não recebe `category_id`, `allocation_id`, percentual ou ponteiro mutável para classificação corrente.

### Classificação simples é um rateio de uma parcela

Não existem dois mecanismos concorrentes de classificação.

Uma classificação integral em uma categoria é representada como um allocation set contendo uma única parcela cujo amount é exatamente o amount do Movement.

Um rateio usa duas ou mais parcelas.

Assim, classificação simples e rateio compartilham o mesmo contrato, histórico e invariantes.

### Parcelas usam Money, não percentual autoritativo

Cada parcela possui:

```text
category_id
Money(amount, currency)
```

O amount de cada parcela é classificação analítica e não autoridade de saldo.

Percentuais podem ser derivados para apresentação, mas não são persistidos como fonte de verdade. Isso evita ambiguidades de arredondamento e permite provar fechamento exato usando o mesmo `Decimal`/`NUMERIC(24,8)` do domínio financeiro.

Para um allocation set válido:

```text
allocation.currency == movement.currency
sign(allocation.amount) == sign(movement.amount)
sum(allocation.amount) == movement.amount
```

Nenhuma parcela pode ser zero.

### Uma categoria aparece no máximo uma vez por versão

Dentro de um allocation set, `category_id` é unique.

Se a UI desejar mostrar várias linhas para a mesma categoria, deve consolidá-las antes de persistir. O primeiro contrato evita linhas semanticamente redundantes e simplifica digest, soma e relatório.

### Audiência da categoria deve conter a audiência do Movement

O vínculo de classificação herda a audiência do Movement. Para não revelar uma categoria invisível a alguém que já pode ler o Movement, a categoria usada precisa ter audiência igual ou mais ampla.

Matriz inicial:

```text
Movement de conta PERSONAL:
  categoria PERSONAL do mesmo owner -> permitida
  categoria HOUSEHOLD                -> permitida

Movement de conta SHARED:
  categoria PERSONAL                 -> proibida
  categoria HOUSEHOLD                -> permitida

Movement de conta HOUSEHOLD:
  categoria PERSONAL                 -> proibida
  categoria HOUSEHOLD                -> permitida
```

Uma categoria `PERSONAL` de outro owner nunca é válida para o Movement.

A categoria precisa estar `ACTIVE` no momento de uma nova classificação ou revisão. Desabilitar uma categoria depois não apaga o histórico existente.

### Primeiro recorte classifica apenas resultado econômico

São elegíveis somente Movements:

```text
role = STANDARD
result_effect IN (INCOME, EXPENSE)
```

`NEUTRAL` fica fora do primeiro contrato. Isso evita que transferências, principal de empréstimo, liquidações e outros movimentos patrimoniais sejam categorizados como receita/despesa por conveniência de UI.

`REVERSAL` também não recebe rateio manual independente. Relatórios que precisem classificar reversões devem derivar a classificação do Movement original, preservando a cadeia econômica sem exigir duplicação manual.

### Allocation set é uma versão imutável

A persistência usa duas relações conceituais:

```text
finance.movement_allocation_sets
finance.movement_allocations
```

O set identifica uma versão completa da classificação de um Movement. As allocations são as parcelas dessa versão.

A primeira versão possui:

```text
revision = 1
supersedes_id = NULL
```

Uma correção não executa UPDATE/DELETE. Ela cria nova versão:

```text
revision = anterior.revision + 1
supersedes_id = anterior.id
```

A nova versão substitui analiticamente a anterior por inteiro. O histórico permanece íntegro.

Não existe ponteiro mutável `current_allocation_set_id`. O conjunto corrente é o nó da cadeia que não possui sucessor.

### Cadeia linear sob concorrência

Um allocation set pode ter no máximo uma sucessora.

A persistence deve serializar revisões concorrentes do mesmo predecessor e proteger a regra também em banco. Duas tentativas com chaves diferentes não podem criar um fork de classificação.

A revisão deve provar ainda que predecessor e sucessor pertencem ao mesmo Movement e que a revisão avança exatamente uma unidade.

### Idempotência separada do resource ID

Criação e revisão exigem uma `idempotency_key` UUID v4 independente dos IDs de allocation set e allocation.

O `request_digest` é SHA-256 de material canônico versionado contendo ator, Movement, predecessor quando houver e todas as parcelas.

As parcelas são ordenadas por `category_id` antes do digest. Portanto, a ordem recebida da API/UI não muda a identidade do request.

Semântica:

```text
mesma key + mesmo digest      -> replay
mesma key + digest diferente  -> conflito fail-closed
```

### Autorização de mutação

Nesta primeira versão, criar ou revisar classificação exige:

- contexto correto de installation e residence;
- membership ativa;
- Movement visível;
- conta do Movement `ACTIVE`;
- operador corrente owner da conta;
- todas as categorias visíveis e `ACTIVE`;
- matriz de audiência satisfeita.

Leitura acompanha a audiência do Movement. O allocation set não possui grants independentes.

### Integridade no PostgreSQL

As invariantes críticas não ficam apenas no Python.

A persistência deve impedir commit quando:

- set/allocation/movement/category cruzam installation ou residence;
- target não é `STANDARD INCOME/EXPENSE`;
- moeda diverge;
- sinal diverge;
- parcela é zero;
- categoria se repete na versão;
- soma das parcelas difere do Movement;
- predecessor pertence a outro Movement;
- revision não é sequencial;
- predecessor já possui sucessora;
- política de audiência não é satisfeita.

Como soma e fechamento dependem de várias rows, a checagem final deve ocorrer por constraint trigger `DEFERRABLE INITIALLY DEFERRED` ou mecanismo equivalente no commit.

Runtime recebe somente `SELECT, INSERT` nas tabelas de classificação. Não recebe `UPDATE` nem `DELETE`.

## Alternativas consideradas

### `category_id` direto em Movement

Rejeitada. Não suporta rateio múltiplo, mistura classificação com ledger e cria incompatibilidade de audiência.

### Persistir percentual

Rejeitada como autoridade. Percentuais exigem regra de arredondamento e podem não fechar exatamente no amount original.

### Permitir UPDATE da classificação atual

Rejeitada. Perde histórico e dificulta auditoria de correções.

### Copiar o Movement para uma tabela categorizada

Rejeitada. Criaria segundo ledger ou segunda representação monetária autoritativa.

### Permitir PERSONAL category em SHARED

Rejeitada. Um viewer compartilhado poderia inferir ou receber material de uma categoria privada que não pertence à sua audiência.

### Classificar NEUTRAL no primeiro recorte

Adiada. NEUTRAL representa efeito patrimonial sem resultado econômico e precisa de dimensões analíticas próprias antes de ser exposto como categorização genérica.

## Consequências positivas

- ledger permanece único e simples;
- classificação simples e rateio usam um mecanismo só;
- soma de parcelas fecha exatamente sem float;
- histórico de correções é preservado;
- não existe fork silencioso de revisão;
- categorias privadas não vazam por Movements de audiência mais ampla;
- transferências não contaminam relatórios de receita/despesa.

## Consequências negativas e riscos

- consultas de categoria precisam selecionar a versão corrente da cadeia;
- persistência exige trigger deferred para fechamento multi-row;
- amounts analíticos existem fora do ledger e precisam ser claramente tratados como não-autoritativos;
- desabilitar categoria exige UI/relatório capaz de exibir histórico sem permitir novo uso;
- categorias `SHARED` continuam não suportadas.

## Validação

A implementação deve cobrir:

- classificação 100%;
- rateio múltiplo;
- fechamento exato contra o Movement;
- moeda e sinal;
- duplicidade de categoria;
- matriz PERSONAL/SHARED/HOUSEHOLD;
- categoria desabilitada;
- target NEUTRAL/REVERSAL;
- replay e conflito de idempotência;
- digest independente da ordem;
- revisão append-only linear;
- concorrência de revisão;
- RLS entre residências;
- runtime sem UPDATE/DELETE;
- downgrade/reupgrade simétricos;
- prova de que nenhum Movement ou saldo é alterado.

## Referências

- #124
- #170
- ADR-0015
- ADR-0016
- ADR-0017
- ADR-0019
- ADR-0020
- `docs/architecture/FINANCIAL_INVARIANTS.md`
- `docs/architecture/FINANCIAL_MOVEMENTS.md`
