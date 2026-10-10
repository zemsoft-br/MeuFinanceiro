# Fluxo de caixa v1 — saldo real e projeção de compromissos conhecidos (#265)

Status: **implementado na branch `feat/financial-cash-flow-265`** (5 batches: domínio e ADR, store e serviço, API, Flutter, hardening e documentação). Decisão: ADR-0031 (Proposed). Pull Request em rascunho; merge e integração ao `develop` **ainda não ocorreram**.

## O que é e o que não é

Uma leitura que mostra, por conta e período, o **saldo real** na data de referência e o efeito dos **compromissos já conhecidos** (recorrências) sobre ele, com risco de saldo negativo e o detalhe de cada evento usado no cálculo.

A projeção **não é**:

- um Movement, uma ocorrência, um saldo persistido ou uma segunda contabilidade;
- uma geração de ocorrências (o GET nunca escreve);
- uma soma entre moedas ou uma conversão cambial;
- uma previsão de cartões, parcelas, empréstimos, orçamentos, metas ou projetos.

`finance.movements` continua o único fato realizado; o saldo continua derivado (ADR-0018/0019). Nenhuma migration, tabela, coluna ou cache foi criada.

## Fontes

| Fonte | Como entra |
|---|---|
| opening balance + Movements antes da janela | saldo inicial da janela (agregado `NUMERIC` exato, sob RLS) |
| opening balance + Movements até a referência | saldo **real** na data de referência |
| Movements da janela (`STANDARD` e `REVERSAL`, inclusive pernas `NEUTRAL`) | eventos `REALIZED`, na ordem do extrato |
| ocorrência `PENDING` com data na janela e `>=` referência | `EXPECTED_OCCURRENCE` na data agendada (snapshot da ocorrência) |
| ocorrência `PENDING` vencida (data `<` referência) | `EXPECTED_OCCURRENCE` na **data de referência**, `overdue = true`, com a data original |
| mês de regra `ACTIVE` (conta `ACTIVE`) sem ocorrência viva, data na janela e `>=` referência | `EXPECTED_RULE` (virtual, valor e versão correntes da regra; nada é gravado) |

Sinal: `INCOME` previsto = `+esperado`; `EXPENSE` previsto = `−esperado`. O realizado usa o amount assinado do Movement.

### Por que persistidas e virtuais

Sem a previsão virtual, um caixa de 90 dias ficaria vazio até o usuário gerar três meses de cada regra. Gerar dentro do GET contrariaria a geração explícita da #254. A previsão virtual é rotulada (origem, regra, versão, mês) e some assim que a ocorrência do mês existe. **Datas passadas nunca são inventadas**: um vencimento anterior à referência sem ocorrência pode ter sido pago por um Movement avulso, então é reportado (`UNGENERATED_PAST_OCCURRENCES`).

### Sem dupla contagem

- `REALIZED`: somente o Movement canônico entra; o evento carrega ocorrência, regra e **valor esperado** para comparação (não somado).
- `SKIPPED`: cobre o mês sem expectativa. `SUPERSEDED`: histórico; vale a regra corrente.
- Estorno: o `REVERSAL` entra na sua data; a ocorrência continua `REALIZED`; nada é reaberto.
- Regra `PAUSED`: não projeta mês novo; sua `PENDING` já gerada continua prevista.
- `NEUTRAL`: altera o saldo de cada conta, soma em `neutralIn`/`neutralOut`, nunca em receita/despesa. Transferência entre contas selecionadas se anula no consolidado; para conta não selecionada, altera o consolidado sem virar despesa. Se a outra perna não for visível ao operador, o `transferId` não é exposto (a RLS da transferência exige as duas contas visíveis) e a perna continua `NEUTRAL`.

## Datas, janela e limites

- Data de referência: data do servidor (`date.today` na composição; relógio injetado). Devolvida em `referenceDate`. Fuso por residência ainda não é modelado.
- Janela inclusiva `[from, through]`, no máximo **92 dias**, `from <= referência`. Padrão: 30 dias a partir da referência. Janela totalmente passada é **histórica** (`NOT_APPLICABLE`, só realizado).
- Janela **relativa**: `days` (1–92), exclusivo com `through`, conta a partir de `from` ou da referência do servidor. Os presets "Próximos 7/30/60/90 dias" usam `days` (30 = padrão, sem parâmetro) e funcionam mesmo antes de qualquer leitura bem-sucedida; "Mês atual" e "Personalizado" exigem a `referenceDate` de uma leitura bem-sucedida.
- Até **50 contas** e **2000 eventos** por leitura. Excedeu: `422 financial cash flow window has too many events` — nunca truncado.
- Calendário canônico das recorrências: dia 31 cai no último dia do mês; 29/02 em ano bissexto.

## Moedas e audiência

Um grupo por moeda (`groups[]`), cada um com contas, totais, série diária, risco e eventos próprios. Sem soma entre moedas.

Contas padrão: `ACTIVE` visíveis. `accountId` explícito precisa ser visível (qualquer status); inexistente, invisível e de outra residência dão o mesmo `404`. Residência e operador vêm da sessão; membership ativa é obrigatória; a RLS forçada de contas, Movements, pernas de transferência, regras e ocorrências decide a audiência antes de qualquer soma (`PERSONAL` só do dono, `SHARED` com grant, `HOUSEHOLD` para membros ativos).

## Estados

`projectionStatus`: `COMPLETE` | `INCOMPLETE` | `NOT_APPLICABLE`.

| `issues[].code` | Severidade | Contagem | Significado |
|---|---|---|---|
| `OPENING_BALANCE_MISSING` | INCOMPLETE | contas | saldos partem de zero; risco não avaliável |
| `RULE_ACCOUNT_INACTIVE` | INCOMPLETE | regras | regra ativa de conta arquivada não projetada |
| `OPENING_BALANCE_AFTER_WINDOW_START` | INCOMPLETE | contas | saldo inicial dentro da janela: dias anteriores sem âncora, fora do risco |
| `OVERDUE_OCCURRENCES` | ATTENTION | ocorrências | previstas vencidas incluídas na referência |
| `UNGENERATED_PAST_OCCURRENCES` | ATTENTION | meses | vencimentos passados sem ocorrência, não projetados |
| `PAUSED_RULES` | ATTENTION | regras | regras pausadas não projetam meses novos |
| `HISTORICAL_WINDOW` | ATTENTION | 1 | janela só no passado |

Numa janela histórica o status é `NOT_APPLICABLE` mesmo com issue `INCOMPLETE` (não há projeção); o cliente mostra as issues e a âncora de cada dia.

## Âncora e risco (revisão R2)

- `days[].anchored`: `true` quando **todas** as contas do grupo têm opening balance com data efetiva até aquele dia (ADR-0018). Antes disso o valor de abertura é aplicado antecipadamente (ou, sem opening balance, o saldo parte de zero): os números aparecem como **estimativa** e nunca entram no risco.
- `risk` (prospectivo): dias ancorados `>=` referência. `historicalRisk`: dias ancorados `<` referência. Ambos existem no grupo e em cada conta (por conta, a âncora é o opening balance da própria conta).
- Cada risco tem `evaluatedDays`; `null` = **não avaliável** (nenhum dia ancorado daquele lado ou nenhum dia daquele lado), nunca "sem déficit".
- Exemplos: janela de outubro com déficit só em 02–03/10 e saldo positivo a partir de 04/10 (referência 10/10) → `historicalRisk.firstNegativeDate = 02/10`, `risk.firstNegativeDate = null`. Opening balance em 05/10 numa janela desde 01/10 → 01–04/10 `anchored = false`, `historicalRisk.evaluatedDays = 5`, status `INCOMPLETE`.

## Persistência e consistência

`FinancialCashFlowStore.read_source` lê tudo em **uma transação `REPEATABLE READ` somente leitura** com número fixo de statements (contexto, membership, contas, opening balances, agregados, Movements da janela, pernas de transferência, ocorrências realizadas e suas duas leituras de derivação, `PENDING`, meses vivos, regras). O domínio verifica `saldo inicial + realizados até a referência == saldo real na referência`; divergência falha fechado (`503` sanitizado). Entradas fora da janela, de conta não selecionada, de outra moeda, duplicadas ou com vínculo de realização inválido também falham fechado.

## API

`GET /api/v1/finance/cash-flow?[from=YYYY-MM-DD][&through=YYYY-MM-DD | &days=N][&accountId=…][&currency=XXX]`

- Parâmetros desconhecidos ou repetidos, datas/moeda malformadas, `days` fora de 1–92 (ou com zero à esquerda, decimal), `days` junto com `through` e janela fora do contrato: `422 invalid financial cash flow request`.
- Sem sessão `401`; sem membership `403`; sem residência primária `409`; conta não visível `404`; limite `422`; falha de banco `503`. Mensagens sanitizadas.
- Não existe `POST`, `PUT`, `PATCH` nem `DELETE` (`405`).

```text
{ referenceDate, from, through, days, calculatedAt, excludedSources[],
  groups[] { currency, projectionStatus, issues[] {code, severity, count, accountIds[]},
             startingBalance, balanceAtReference, closingBalance,
             totals { realizedIncome, realizedExpense, neutralIn, neutralOut, realizedNet,
                      expectedIncome, expectedExpense, expectedNet, overdueCount, overdueNet,
                      recurrenceRealizedCount, recurrenceRealizedExpected, recurrenceRealizedActual,
                      realizedCount, expectedCount },
             risk | null, historicalRisk | null
                  // cada um: { minimumBalance, minimumBalanceDate, firstNegativeDate,
                  //            negativeDays, evaluatedDays }
             accounts[] { accountId, name, accountType, visibilityScope, status, hasOpeningBalance,
                          openingBalanceDate, startingBalance, balanceAtReference, realizedNet,
                          expectedNet, closingBalance, risk | null, historicalRisk | null },
             days[] { date, opening, realizedIncome, realizedExpense, expectedIncome, expectedExpense,
                      neutralNet, closing, projected, anchored, negative },
             events[] { date, kind, accountId, amount, resultEffect, description, movementId,
                        movementRole, reversalOfId, transferId, occurrenceId, recurrenceId,
                        ruleVersion, periodStart, scheduledDate, overdue, expectedAmount,
                        balanceAfter, accountBalanceAfter } } }
```

Dinheiro sempre `{amount: "decimal", currency}`. Despesa e receita são magnitudes líquidas de estornos (podem ser negativas quando o estorno de um período anterior cai na janela).

## Cliente Flutter

Tela **Fluxo de caixa** (`/app/financas/fluxo-de-caixa`, atalho em Finanças; a IA canônica prevê `/app/planejamento/fluxo-caixa`, mas as telas de planejamento já entregues vivem sob `/app/financas`):

- aviso fixo: somente leitura, previsto não altera saldo nem extrato, fontes excluídas listadas;
- período (7/30/60/90 dias via `days`, mês atual, personalizado até 92 dias), filtro de contas (inclusive arquivadas, explicitamente) e moeda;
- saldo real × projetado, realizado × previsto;
- **dois cartões de risco**: *Risco de saldo negativo* (prospectivo, a partir da referência) e *Saldo negativo já ocorrido (histórico)* — "fato realizado, não previsão" —, cada um com o consolidado e as contas; avaliação parcial dita ("Avaliados N de M dias"); `null` vira **"não avaliável"**, nunca "sem déficit";
- dias e saldos sem âncora rotulados como **estimativa** (série diária, resumo, contas e detalhe do evento) e nunca destacados como negativos;
- status e issues em texto; evolução diária (dias com movimento ou todos); eventos por dia com origem (*Realizado*, *Previsto · ocorrência gerada*, *Previsto pela regra · não gerado*, *Prevista vencida*) e diálogo de detalhe;
- listas longas exibidas em páginas de 100 com "Exibindo N de M" (nunca cortadas em silêncio);
- estados: carregando, vazio, erro, indisponível, sessão, acesso, residência, conta indisponível, resposta inválida, recusa do servidor (422 — inclusive na **primeira** leitura: contas e presets relativos continuam utilizáveis para reduzir a seleção e recuperar) e "dados possivelmente desatualizados" após falha de atualização.

Contratos do cliente: só `GET`; nenhum `double`; nenhuma soma de dinheiro; validação estrita do formato (chaves fechadas iguais aos DTOs Python — conferidas por teste de contrato —, moeda do grupo, dias contíguos, `projected` coerente com a referência, `anchored` coerente com as datas de abertura, riscos coerentes com os dias avaliados, eventos ordenados e coerentes com a origem); presets relativos enviam `days` e nunca uma data do cliente; janela padrão conferida (`from == referenceDate`, comprimento pedido); respostas obsoletas descartadas; sem retry automático.

## Evidências (validação local; sem GitHub Actions)

| Escopo | Testes |
|---|---|
| domínio puro (`packages/finance/tests/test_cash_flow.py`) | 59 |
| store PostgreSQL 18.4, role `NOBYPASSRLS`, RLS forçada (`packages/persistence/tests/test_financial_cash_flow.py`) | 18 |
| serviço (`apps/api/tests/test_financial_cash_flow_service.py`) | 8 |
| HTTP real + PostgreSQL (`apps/api/tests/test_financial_cash_flow_postgres.py`) | 32 |
| contratos de qualidade (backend, Flutter e paridade DTO Python × parser Dart) | 18 |
| Flutter (API 51, controller 17, tela 16) | 84 |

Provas relevantes: paridade do saldo real com `derive_financial_account_balance_and_statement`; leitura não escreve (contagem de todas as tabelas `finance`); snapshot sob escrita concorrente entre statements; transação `read only` + `repeatable read`; número de statements idêntico para 1 ou dezenas de contas/regras/Movements; 5 contas × 2 anos de histórico diário + 90 regras em ~segundos sob RLS com o índice `ix_finance_movements_account_effective` no plano; transferência para conta invisível sem vazamento; membership revogada falha fechado.

**Smoke vertical HTTP** (`test_smoke_the_issue_vertical_over_http`): saldo inicial 1000 → receita 2000 → despesa 300 → transferência 500 para a poupança → aluguel mensal 2500 (outubro gerado) e salário 1500 (regra) → saldo real 2200 na referência → déficit projetado a partir de 20/10 (−1300) → **Registrar** 2450 cria exatamente um Movement e cobre outubro (sem previsão duplicada) → estorno: o `REVERSAL` aparece, nada é reaberto → saldo real na referência igual ao saldo canônico da conta.

**Smoke na pilha real** (API uvicorn + PostgreSQL descartável + Flutter Web release, navegador): login local, dados criados só pela API pública, tela renderizada em 1920×1080 com saldo real, projetado, risco por conta, filtros de período e troca de moeda. O smoke revelou um defeito (grupo sem saldo inicial dizia "Saldo sem déficit"), corrigido com regressão.

## Limitações conhecidas (v1)

- Previsão virtual usa o valor corrente da regra (sem reajuste, média ou faixa).
- Data de referência é a do servidor; sem fuso por residência nem "as-of" histórico.
- Janela de até 92 dias e 2000 eventos; sem paginação por cursor dos eventos.
- Cartões, faturas, parcelas, empréstimos, metas (contribuição planejada) e orçamentos não entram.
- Sem cheque especial/limites, cenários, calendário dedicado, alertas ou exportação.
- O consolidado soma contas da mesma moeda visíveis ao operador; não há "visão da casa" separada da visão pessoal.

## Estado do trabalho

| Batch | Escopo | Estado |
|---|---|---|
| 1 | domínio puro, DTOs, ADR-0031 | concluído |
| 2 | store snapshot read-only, serviço, PostgreSQL/RLS/desempenho | concluído |
| 3 | `GET /finance/cash-flow`, HTTP real, contrato de qualidade | concluído |
| 4 | tela Flutter, controller, cliente estrito | concluído |
| 5 | hardening, smoke vertical, smoke na pilha real, documentação | concluído |
| R2 | revisão da PR #266: primeira leitura 422 recuperável (`days`), risco prospectivo × histórico, âncora do opening balance (`anchored`, `INCOMPLETE`) | concluído |

### Revisão R2 (PR #266)

- **P2-1 — primeira leitura 422**: os filtros dependiam de uma `referenceDate` que só existe após leitura bem-sucedida. Agora contas e presets relativos (`days`, incluindo *Próximos 7 dias*) ficam habilitados após qualquer recusa; mês atual/personalizado esperam a data do servidor, com aviso. Nenhuma data é inventada no cliente.
- **P2-2 — déficit histórico como risco futuro**: o risco passou a ser dividido em `risk` (dias `>=` referência) e `historicalRisk` (dias `<` referência), no grupo e por conta; a tela mostra dois cartões distintos.
- **P2-3 — saldo de abertura posterior ao início**: dias antes da âncora têm `anchored = false`, ficam fora de todo risco, aparecem como estimativa e `OPENING_BALANCE_AFTER_WINDOW_START` passou a `INCOMPLETE`.
- Achado na R2: `_enumByWire` limitava enums a 32 caracteres e `OPENING_BALANCE_AFTER_WINDOW_START` tem 34 — qualquer resposta com esse aviso seria rejeitada como inválida. Limite elevado a 64 e coberto por teste de contrato.
