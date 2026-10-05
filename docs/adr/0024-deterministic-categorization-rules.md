# ADR-0024 — Regras determinísticas de categorização com proveniência append-only

- Status: Accepted
- Data: 2026-10-05
- Decisores: mantenedores

## Contexto

A #170/#245 entregaram classificação e rateio manual de Movements: `finance.movement_allocation_sets` / `movement_allocations` são a única autoridade da classificação corrente, sempre append-only (ADR-0022), com auditoria financeira transacional mínima (ADR-0023).

A primeira capacidade da Fase 2 (#180) é classificar automaticamente Movements recorrentes **sem** criar uma segunda autoridade, sem reescrever o ledger, sem depender de IA ou de provider externo e sem produzir resultado ambíguo. A decisão precisa responder: onde a regra mora, como ela casa, o que acontece num empate, como a escrita acontece, como se rastreia a origem e o que a auditoria financeira deve (ou não) conter.

## Decisão

### A regra é uma versão semântica imutável

`finance.categorization_rules` é residence-scoped e provider-neutral. A semântica (conta opcional, `INCOME`/`EXPENSE` opcional, `EXACT`/`CONTAINS` sobre a descrição, categoria-alvo, prioridade) nunca é editada: o runtime só pode mover uma regra de `ACTIVE` para `DISABLED` (grant de UPDATE restrito a `status`, `disabled_at`, `disabled_by_operator_id`, mais trigger que recusa qualquer outra mudança e qualquer outra transição). Mudar uma condição, a prioridade ou a categoria é **desabilitar e criar outra regra**. Cada `rule_id` identifica exatamente a semântica aplicada. Não existe `PUT`, `PATCH` ou `DELETE`.

### Matching único, no domínio

A normalização é definida uma vez em `meufinanceiro_finance.categorization_rules`: trim de whitespace Unicode externo, composição NFC e `casefold` determinístico (NFC antes e depois). Acentos, pontuação e espaçamento interno são preservados e nada depende de locale. `EXACT` compara a descrição normalizada inteira; `CONTAINS` testa substring. O texto digitado é preservado (apenas trim externo) para UX. Preview e apply usam a **mesma** função; o Flutter não casa nada.

### Prioridade e ambiguidade falham fechado

Regras inativas, de outra conta, de outro efeito ou com categoria-alvo inutilizável (`DISABLED` ou incompatível com a audiência da conta) são descartadas **antes** da resolução. Vence a maior prioridade se for **única**; empate no topo é `AMBIGUOUS` e nada é escrito. `created_at`, UUID e ordem de consulta nunca desempatam. Duas regras idênticas empatam.

### Execução explícita: preview somente leitura e apply confirmado

Nada roda em background, na criação ou na importação. `preview` não escreve, não reserva e não garante nada. `apply` recebe os pares `(movementId, ruleId)` que o operador confirmou e reavalia **tudo** a partir do estado canônico dentro de uma transação por Movement, sob o mesmo lock de linha (`finance.lock_standard_movement_for_allocation`) que serializa a classificação manual:

1. Movement elegível (STANDARD `INCOME`/`EXPENSE`, conta do operador, ACTIVE) — senão `INELIGIBLE`;
2. já existe allocation set corrente — `ALREADY_CLASSIFIED`, sem revisão;
3. regras/categorias reavaliadas — `NO_MATCH`, `AMBIGUOUS` ou, se a regra vencedora difere da confirmada, `CONFLICT`;
4. escrita do **mesmo** allocation set revisão 1 da classificação manual (um share com o Money exato do Movement), a proveniência e o evento `ALLOCATION_SET_CREATED`, atomicamente.

O resultado por Movement (`CLASSIFIED`, `ALREADY_CLASSIFIED`, `AMBIGUOUS`, `NO_MATCH`, `INELIGIBLE`, `CONFLICT`, `FAILED`) é devolvido para que um resultado parcial nunca seja apresentado como sucesso total. Uma regra só produz a **primeira** classificação; um override manual posterior segue pelo fluxo append-only da #245 e nenhuma regra o reaplica ou reverte.

### Proveniência é evidência, não autoridade

`finance.movement_allocation_rule_origins` tem 0 ou 1 linha por allocation set (`allocation_set_id` PK), apenas identidade, escopo e `rule_id` (nenhum valor, descrição ou payload copiado), append-only (SELECT/INSERT para o runtime) e com RLS forçada. Um trigger exige: revisão 1, regra `ACTIVE` (travada `FOR SHARE`, de modo que um `disable` concorrente se serializa com a aplicação), condições da regra válidas para o Movement e um único share igual ao alvo da regra com o Money do Movement. Ausência de origin significa classificação não atribuída por regra (por exemplo, manual). A origin nunca decide qual classificação é a corrente: só vale para o set corrente, e um override manual a deixa para trás como história.

### Idempotência e concorrência

A chave de idempotência de cada aplicação é derivada deterministicamente de `(rule_id, movement_id)` (UUID v4-shaped), com contrato explícito e teste; não há geração aleatória em retry. Replay do apply nunca cria revisão (o Movement já classificado é `ALREADY_CLASSIFIED`). Aplicação concorrente com classificação manual ou com outra regra serializa no lock do Movement: exatamente uma classificação vence e nenhuma revisão automática é criada. A criação de regra aceita `idempotencyKey` (replay seguro; reutilização com outro material é `409`), para que um retry explícito após resultado ambíguo não duplique regras. O cliente nunca reenvia uma escrita ambígua automaticamente.

### Lifecycle de regra fica fora da auditoria financeira fechada

Criar/desabilitar uma regra não é uma mutação do ledger nem da classificação. `FinancialAuditEventDraft` e `finance.audit_events` **não** foram ampliados: a regra carrega seu próprio autor e timestamps (`created_by_operator_id`, `created_at`, `disabled_by_operator_id`, `disabled_at`). A mutação financeira efetiva (o allocation set) continua auditada como `ALLOCATION_SET_CREATED`, sem `rule_id` nem detalhe de matching. Há testes que provam que o lifecycle não escreve evento financeiro e que cada origin corresponde a exatamente um evento auditado do operador que aplicou.

### Autorização

Ator e residência vêm do servidor. A regra é visível somente se a categoria-alvo (e a conta, quando houver) forem visíveis ao operador (RLS); somente o criador desabilita. Preview e apply só existem para o dono de uma conta ACTIVE, isto é, onde o operador já poderia classificar manualmente; conhecer um `rule_id` nunca prova autorização. Categoria `PERSONAL` de outro owner nunca é alvo válido e `HOUSEHOLD` segue a matriz de audiência da ADR-0022.

## Alternativas consideradas

- **`rule_id` em `movement_allocation_sets` ou `category_id` em `finance.movements`:** cria uma segunda fonte de verdade e reabre o ledger/allocation. Rejeitada.
- **Regra editável in-place:** perde a rastreabilidade de qual semântica produziu cada classificação. Rejeitada em favor de desabilitar + criar.
- **Ampliar o audit financeiro com `rule_id`/metadata:** transforma o audit mínimo em log genérico. Rejeitada.
- **Aplicar em lote numa única transação:** um conflito reverteria o lote inteiro e os triggers diferidos de integridade só falham no commit. Rejeitada: uma transação por Movement com resultado por item.
- **Desempate por data/UUID:** escolhe regra arbitrariamente. Rejeitada; empate é `AMBIGUOUS`.
- **Execução em background ou na importação:** fora do recorte v1.
- **Regex, fuzzy, faixas de valor/data, múltiplas categorias por regra:** fora do recorte; podem ser refinados depois sobre esta semântica estável.

## Consequências positivas

- Classificação automática explicável, determinística e com a mesma autoridade e o mesmo histórico da manual.
- Ambiguidade, concorrência e replay falham fechados sem overwrite.
- Origem rastreável sem segunda fonte de verdade e sem copiar dados financeiros.

## Consequências negativas e riscos

- Mudar uma regra exige criar outra; o histórico de regras desabilitadas cresce (sem histórico visual completo nesta entrega).
- Apply faz uma transação por Movement (limite de 200 pares por requisição); listas maiores exigem aplicar e pré-visualizar de novo.
- Duas regras equivalentes ativas empatam e bloqueiam a classificação até uma ser desabilitada (efeito intencional do fail-closed).
- A visibilidade de regras segue a audiência da categoria-alvo e da conta; operadores diferentes da mesma residência podem enxergar conjuntos de regras diferentes.

## Validação

Domínio (matching, normalização, prioridade, empate, elegibilidade), PostgreSQL com role não-superuser e RLS forçada (lifecycle, imutabilidade por privilégio e por trigger, proveniência forjada, corrida manual-vs-regra, applies concorrentes, rollback quando a proveniência falha, `FOR SHARE` bloqueando `disable`), migration downgrade/re-upgrade, API ponta a ponta (smoke vertical da #247), Flutter (sem sucesso otimista, sem retry automático, resultado parcial visível, leitura bulk sem N+1) e testes de contrato; os caminhos críticos foram verificados por mutação dirigida. Ver `docs/architecture/FINANCIAL_CATEGORIZATION_RULES.md`.

## Referências

- #124
- #170
- #171
- #180
- #245
- #247
- ADR-0022
- ADR-0023
- `docs/architecture/FINANCIAL_CATEGORIZATION_RULES.md`
- `docs/architecture/FINANCIAL_MOVEMENT_CLASSIFICATION_API.md`
