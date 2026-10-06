# ADR-0026 — Orçamentos mensais por categoria como planejamento derivado do ledger

- Status: Accepted
- Data: 2026-10-06
- Decisores: mantenedores

## Contexto

A Fase 2 (#180) pede comparar planejado e realizado. O ledger (`finance.movements`, ADR-0019/0020) é a única autoridade monetária; a classificação corrente (`movement_allocation_sets`, ADR-0022) é a única autoridade analítica; regras (ADR-0024) e caixa de pendências (ADR-0025) são derivadas ou sugestivas. O roadmap exige que orçamento seja planejamento/analytics e nunca um segundo ledger.

A decisão precisa responder: onde mora o plano, como o realizado é obtido sem virar estado, como estornos entram sem classificar `REVERSAL`, quem lê e quem escreve, como evitar perda de atualização, e como o resumo avisa que o realizado pode estar incompleto.

## Decisão

### O plano é persistido; o realizado nunca é

`finance.budgets` guarda identidade e versão; `finance.budget_lines` guarda o planejado por `(category_id, result_effect)`. Não existe Movement fictício, saldo planejado, `budget_id` ou `category_id` em `finance.movements`, nem coluna `realized`, `remaining` ou cache monetário. O realizado é recalculado a cada leitura a partir do ledger e do **allocation set corrente** (o nó da cadeia sem sucessor). Reclassificar altera o próximo resumo e nada mais.

### Contrato v1

- período `MONTHLY`; `period_start` é o primeiro dia do mês (CHECK no banco) e o fim exclusivo é derivado no servidor;
- moeda explícita por orçamento; só Movements dessa moeda entram; não há conversão cambial (outra moeda fica fora, nunca é convertida);
- base de data pertence ao orçamento: `CASH` usa `effective_date`, `COMPETENCE` usa `competence_date`; o cliente não infere;
- linhas: categoria **exata** (sem subtree), `INCOME` ou `EXPENSE`, `planned_amount > 0` em `NUMERIC(24,8)`; 1 a 100 linhas; únicas por `(category_id, result_effect)`;
- unicidade material: um plano por residência, audiência (e dono, se `PERSONAL`), moeda, mês e base;
- `SHARED` não existe em orçamentos.

### Audiência

| Orçamento | Leitura | Escrita | Categoria da linha | Contas somadas |
|---|---|---|---|---|
| `PERSONAL` | só o dono | só o dono | `PERSONAL` ativa do mesmo dono | contas `PERSONAL` do dono |
| `HOUSEHOLD` | membros ativos | **só o dono (criador)** | `HOUSEHOLD` ativa | contas `HOUSEHOLD` |

Ler um orçamento da casa nunca implica escrever (`canEdit` é decidido no servidor e no banco). Fixar as contas somadas pela audiência do orçamento faz todo membro ver os mesmos números num orçamento da casa e impede que gastos pessoais de alguém vazem para um total compartilhado; contas `SHARED` ficam fora da v1. Conhecer um id nunca prova autorização: orçamento ou categoria inexistente, invisível ou incompatível são o mesmo erro sanitizado. RLS é `FORCE`d e fail-closed; o runtime recebe `SELECT, INSERT` e `UPDATE` somente de `name, version, updated_at, updated_by_operator_id`; não há `DELETE`.

### Escrita: replay-safe e CAS sem perda de atualização

- criar usa `idempotencyKey` UUID v4 e digest SHA-256 do material canônico (independente da ordem das linhas): mesma chave e mesmo material é replay; mesma chave com outro material, ou outro operador, falha fechado (`409`). Mesmo sem chave igual, o mês já planejado é `409`;
- editar é substituição completa de nome e linhas com `expectedVersion` obrigatório: `UPDATE ... WHERE version = :expected` é o CAS; versão antiga é `409` sem gravar nada. Escopo, dono, moeda, mês e base são imutáveis;
- as linhas são **append-only por revisão**: cada versão tem seu conjunto completo e o corrente é o de `revision = budgets.version`. Gatilhos do banco exigem versão + 1, identidade imutável, linhas só na revisão escrita na mesma transação, categoria ativa e compatível e 1 a 100 linhas no commit. Revisões antigas permanecem (nada é apagado);
- o Flutter nunca reenvia automaticamente nem refaz a edição sobre a versão nova após `409`; relê o estado canônico e exige nova edição explícita.

### Realizado derivado e consciente de estornos

Para cada linha, o realizado é a soma de **magnitudes positivas** das allocations correntes do Movement `STANDARD` da categoria e do efeito exatos, no mês pela base de data do orçamento. Um rateio conta só a parcela da categoria. `NEUTRAL` nunca entra.

`REVERSAL` não é classificado (ADR-0022 já manda derivar do original). Sua contribuição é a **negativa** da allocation corrente do `STANDARD` que ele estorna, posicionada na **data do próprio estorno** conforme a base. Logo:

- estorno integral no mesmo mês do original zera o impacto exatamente uma vez (sem dupla contagem);
- estorno em mês posterior credita o mês do estorno (o realizado desse mês pode ser negativo; o do mês original permanece);
- reclassificar o original move original e estorno juntos;
- a data de caixa e a de competência do estorno são independentes, como no ledger.

Isto cabe no contrato atual (o estorno é integral, `reversal_of_id` único e mesma conta/moeda/efeito); não foi necessário alterar ADR anterior nem bloquear.

### Cobertura de classificação

O resumo traz, por período/moeda/audiência e **fora das linhas**: `unclassifiedExpenseCount/Amount` e `unclassifiedIncomeCount/Amount`. Cada `STANDARD` sem allocation set soma `+|valor|`; cada `REVERSAL` de original sem classificação cujo original está fora do mês soma `-|valor|`; um par original/estorno ambos dentro do mês se cancela (contagem e valor). O valor é, portanto, um líquido que só fica negativo no caso raro de estorno em mês diferente. É um alerta e uma ponte para a caixa de pendências (#249); não é um orçamento nem atribui valor a linha.

### Leitura consistente e custo

Linhas, orçamento e ledger são lidos numa transação `REPEATABLE READ` somente leitura com número fixo de statements (contexto, membership, orçamento, linhas, realizado, cobertura). O realizado é um agregado SQL com CTEs materializadas e leitura das parcelas dos Movements do mês por `movement_id = ANY(ARRAY(...))` (uma varredura por tabela). Isso importa porque, sob RLS forçada, um plano com loops aninhados reavalia a cadeia de políticas das allocations a cada nova varredura: a primeira versão (join por `COALESCE(reversal_of_id, id)` e depois loops por linha) levou de segundos a **mais de 10 minutos** em 60 mil Movements. A migration `0024_budget_realization_indexes` cria só um índice de desempenho (`movement_allocations(residence_id, movement_id)`).

Medição local (PostgreSQL 18.4, role não-superuser, RLS forçada, 60 mil Movements, ~1,9 mil no mês, 20 linhas): leitura completa ~0,1 s (realizado ~24 ms, cobertura ~47 ms no servidor); o custo acompanha o mês, não o ledger (triplicar o ledger fora do mês muda buffers < 60%, provado em teste).

### Fora do audit financeiro fechado

Assim como as regras (ADR-0024), o ciclo de vida de orçamento não é mutação do ledger nem da classificação: `finance.audit_events` não é ampliado. O orçamento carrega autoria (`owner_operator_id`, `updated_by_operator_id`) e timestamps, e cada revisão de linhas é preservada.

## Alternativas consideradas

- **Orçamento como Movements futuros ou saldo planejado:** criaria segundo ledger. Rejeitada.
- **`budget_id` / `category_id` em `finance.movements`:** viola ADR-0022. Rejeitada.
- **Persistir ou cachear o realizado:** divergiria da classificação a cada revisão. Rejeitada.
- **Classificar `REVERSAL` ou deduzir o estorno por sinal:** duplica fato classificatório. Rejeitada; deriva-se do original.
- **Escrita da casa por qualquer membro:** exigiria política de edição concorrente e de autoria própria; fica para decisão posterior (o CAS já protegeria de perda de atualização).
- **Subtree/rollup, envelopes, rollover, FX, tags, metas:** fora da v1 por risco de dupla contagem e contratos próprios.
- **Função `SECURITY DEFINER` para acelerar o realizado:** abriria uma superfície que ignora RLS; o plano corrigido atinge o custo sem isso. Rejeitada.
- **`DELETE` de orçamento:** destrutivo; arquivamento será refinado depois.

## Consequências

- planejado e realizado vivem em camadas distintas; o ledger não muda por causa de orçamento;
- o realizado pode ser negativo em mês de estorno tardio e a cobertura é um líquido: a UI mostra os números como o servidor entrega;
- uma edição simultânea perde para o CAS com `409` e o usuário relê antes de editar;
- cada orçamento acumula revisões de linhas (pequenas); a limpeza fica para a política de ciclo de vida.

## Validação

Domínio, schema, RLS entre residências e audiências, CAS (incluindo concorrência), replay e conflito de idempotência, unicidade material, agregação (simples, rateio, outra moeda, `NEUTRAL`, limites do mês, caixa × competência, reclassificação, estornos no mesmo mês, tardios, por base e de não classificados), plano de execução, contagem de statements, API HTTP, contratos de qualidade e Flutter (estados, conflito, somente leitura, cobertura, categorias incompatíveis).

## Referências

- #180, #252
- ADR-0015, ADR-0016, ADR-0019, ADR-0020, ADR-0022, ADR-0023, ADR-0024, ADR-0025
- `docs/architecture/FINANCIAL_BUDGETS.md`
