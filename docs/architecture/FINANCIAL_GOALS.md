# Metas financeiras com destinação virtual (#260)

Status: **em implementação (#260)** na branch `feat/financial-goals-260`. Decisão: ADR-0029. Esta página descreve o contrato; ela é completada a cada batch (domínio → persistência → API → Flutter). Pull Request, merge e integração ao `develop` **ainda não ocorreram**.

## O que é e o que não é

Uma meta é **planejamento**: título, moeda, alvo positivo, prazo opcional, dono e audiência. A pessoa **destina virtualmente** parte do saldo já existente de uma conta a essa meta e acompanha quanto foi destinado e quanto falta.

A destinação virtual **não é**:

- um Movement, uma transferência, uma receita ou uma despesa;
- uma linha de orçamento ou uma ocorrência de recorrência;
- um saldo bancário, uma conta nova ou dinheiro bloqueado.

`finance.movements` continua o único ledger realizado e o saldo de conta é sempre derivado (ADR-0018/0019). Destinar ou liberar **não muda nenhum saldo**. Projetos (orçamento classificatório, fases e marcos) ficam para outra child.

## Persistência

`finance.goals` (planejamento, CAS por `version`) e `finance.goal_allocation_events` (histórico append-only). Não existe coluna de destinado, restante ou saldo virtual: tudo é derivado dos eventos.

| `finance.goals` | |
|---|---|
| `id` | UUID v4 |
| `installation_id`, `residence_id`, `owner_operator_id` | escopo e dono (FK composta com a residência e a membership) |
| `visibility_scope` | `PERSONAL` \| `HOUSEHOLD` |
| `title`, `description` | 1–96 e 0–280 caracteres, sem controle |
| `currency`, `target_amount` | moeda explícita, `NUMERIC(24,8) > 0` |
| `target_date` | opcional |
| `version` | CAS; começa em 1 e só avança de um em um |
| `idempotency_key`, `request_digest` | criação replay-safe (único por instalação) |
| `updated_by_operator_id`, `created_at`, `updated_at` | autoria |

| `finance.goal_allocation_events` | |
|---|---|
| `id` | UUID v4 |
| `goal_id`, `account_id` | meta e conta (FK composta; a conta ancora a moeda) |
| `kind` | `ALLOCATE` (valor positivo) \| `RELEASE` (valor negativo) |
| `amount`, `currency` | valor assinado em `NUMERIC(24,8)`, nunca zero |
| `actor_operator_id`, `created_at` | autoria |
| `idempotency_key`, `request_digest` | replay-safe (único por instalação) |

Sem `UPDATE` nem `DELETE` nos eventos (grants e gatilhos). O runtime atualiza em `goals` somente `title, description, target_amount, target_date, version, updated_at, updated_by_operator_id`.

## Audiência e contas elegíveis

| Meta | Leitura | Escrita | Conta que pode lastreá-la |
|---|---|---|---|
| `PERSONAL` | só o dono | só o dono | `PERSONAL` do mesmo dono, mesma moeda |
| `HOUSEHOLD` | membros ativos | só o dono | `HOUSEHOLD` do mesmo dono, mesma moeda |

`SHARED` nunca é elegível. Uma meta usa até 25 contas da mesma moeda; uma conta sustenta várias metas. Nova destinação exige conta `ACTIVE`; liberar um vínculo histórico funciona depois de arquivar a conta. Membership revogada, residência diferente e id forjado falham fechado com o mesmo erro sanitizado.

## Disponibilidade e concorrência

`disponível(conta) = saldo canônico − Σ destinado (todas as metas, líquido de liberações)`.

- O saldo vem da função canônica `derive_financial_account_balance_and_statement` (abertura + Movements + estornos + pernas de transferência `NEUTRAL`), lida na **mesma transação** da escrita, pelos mesmos leitores do ledger. Não há agregação própria.
- Toda destinação e liberação adquire `pg_advisory_xact_lock` por conta antes de ler saldo e total destinado, então duas destinações concorrentes à mesma conta se serializam e a segunda enxerga a primeira. O mesmo lock é adquirido pelo gatilho do banco.
- `ALLOCATE` só passa se `valor ≤ disponível`. `RELEASE` só passa se `valor ≤ destinado (meta, conta)`: nunca há saldo virtual negativo.
- Movements normais **nunca** são bloqueados nem reescrevem eventos.

## Saldo que cai depois

Se despesas posteriores derrubam o saldo abaixo do total destinado, o resumo mostra `backingStatus: INSUFFICIENT` e o `shortfall` da conta, sem rebalancear nem apagar eventos e sem afirmar garantia bancária. Enquanto a conta estiver insuficiente, novas destinações nela são recusadas; liberar continua permitido.

## Limites explícitos (sem truncamento)

| Limite | Valor |
|---|---|
| metas por dono e residência | 200 |
| contas por meta | 25 |
| eventos por meta | 500 |

Ao exceder, a escrita falha com `409`; um estado já fora do limite falha na leitura com `503` sanitizado, nunca cortado.

## Progresso e arredondamento

`progressPercent = destinado / alvo × 100`, `HALF_UP` em 2 casas, **sem teto** (pode passar de 100). `remainingTarget = max(alvo − destinado, 0)` e `surplus = max(destinado − alvo, 0)`. Estados: `NOT_STARTED`, `IN_PROGRESS`, `REACHED`, `EXCEEDED`. Reduzir o alvo abaixo do destinado resulta em `EXCEEDED`, sem ajuste automático.

## Prazo

Ao criar, ou ao alterar o prazo, a data deve estar entre `hoje(UTC) − 1 dia` e 100 anos à frente. Manter o prazo já gravado numa edição não revalida.
