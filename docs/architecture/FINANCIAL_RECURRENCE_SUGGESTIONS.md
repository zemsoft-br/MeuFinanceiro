# Sugestões assistidas de recorrência — padrão detectado, confirmação explícita

Status: **em implementação (#256)** na branch `feat/finance-assisted-subscriptions-256`; batches 1 (domínio, detector puro, fingerprint e ADR), 2 (decisões persistidas, RLS e store) e 3 (API) concluídos. Pull Request, merge e integração ao `develop` **ainda não ocorreram**.

Normativo: ADR-0028 (e ADR-0027 para a recorrência criada). Este documento descreve o contrato do detector, do fingerprint e das decisões. Nenhuma regra financeira anterior foi alterada.

## Definição

Uma **sugestão** é um padrão mensal provável, **derivado na leitura** de Movements `STANDARD` `EXPENSE` já realizados e visíveis ao operador. Ela **não é** Movement, ocorrência nem recorrência; não altera saldo, extrato, classificação nem orçamento; nunca é aceita sozinha; `GET` nunca escreve; não há job nem processo de fundo. O único efeito possível é o usuário **confirmar** a criação de uma recorrência canônica da #254 (ou **dispensar** a sugestão). Detecção é provider-neutral: sem Pluggy, merchant, fuzzy, ML, LLM ou pontuação opaca.

## Detector v1

Implementado como função pura (`detect_recurrence_suggestions`, em `meufinanceiro_finance.recurrence_suggestions`): dado o mesmo conjunto de observações e a mesma data injetada, devolve o mesmo resultado, independentemente da ordem. Não lê relógio nem fuso.

**Entrada elegível** (filtrada por quem chama, sob a RLS do operador): `STANDARD` `EXPENSE` de conta `ACTIVE`, com data efetiva entre o primeiro dia do mês de `hoje − 11 meses` e `hoje` (12 meses civis; nada no futuro). Excluídos: `REVERSAL`, `INCOME`/`NEUTRAL`, `STANDARD` já revertido, Movement ligado a `finance.recurrence_occurrences` e descrição ausente, vazia ou só espaços após normalizar.

**Agrupamento** (nunca entre contas): `(conta, EXPENSE, moeda, descrição normalizada)`. Normalização reutilizada de `normalize_categorization_text`: trim externo → NFC → `casefold` → NFC (acentos, pontuação e espaços internos preservados). `Streaming`, `  STREAMING` e `streaming ` são o mesmo grupo; `Streaming+` e `Streamingg` não são.

**Critério** (todos obrigatórios):

| Regra | Efeito se falhar |
|---|---|
| a *corrida* final de meses civis consecutivos (até a última observação) tem ≥ 3 meses e **exatamente uma** observação por mês | sem sugestão |
| a corrida termina no mês atual ou no anterior | sem sugestão (padrão que parou) |
| o último mês tem uma única observação | sem sugestão (ambíguo) |
| as datas cabem numa janela de cobrança de ±3 dias em torno de um dia âncora | sem sugestão |
| nenhuma recorrência da conta cobre o mesmo grupo (conta, `EXPENSE`, moeda, descrição normalizada; qualquer status) | sem sugestão |

Uma lacuna, ou um mês com duas cobranças, **antes** da corrida só encerra a corrida: valem os meses depois dela.

**Dia âncora.** Um dia `D` (1..31) explica uma observação no mês `M` e dia `d` com desvio `|min(D, último_dia(M)) − d|`, então uma cobrança no dia 31 que cai em 28/29/30 em meses curtos tem desvio zero. `D` é aceito se o maior desvio for ≤ 3. Entre os aceitos vence o de menor maior desvio, depois menor desvio total, depois menor dia: escolha total, independente da ordem. Exemplos: `10, 11, 12` → 11; `31/07, 31/08, 30/09` → 31; `31/12, 31/01, 28/02` → 31; `30/01, 28/02, 30/03` → 30; um espalhamento de sete dias não tem âncora e não gera sugestão.

**Valor.** Pode variar e é evidência: expõe-se cada valor e data observados (na ordem), mínimo, máximo, último valor, `suggestedExpectedAmount` (= último valor observado) e `amountBehavior` (`FIXED` se todos iguais, senão `VARIABLE`). Tudo `Decimal`, nunca `float`.

**Motivos** (`reasonCodes`, enumerados; sem confiança numérica): `EXACT_DESCRIPTION`, `CONSECUTIVE_MONTHS`, `ONE_PER_MONTH`, `DAY_WINDOW` e `AMOUNT_FIXED` ou `AMOUNT_VARIABLE`.

**Saída:** `fingerprint`, conta, dono da conta, descrição exibida (a da última observação), descrição normalizada, moeda, evidências (`movementId`, data, valor), `suggestedDayOfMonth`, `suggestedExpectedAmount`, `amountBehavior`, mínimo, máximo, último, `reasonCodes`, `canAccept` (somente o dono da conta) e o `evidenceDigest` do que foi mostrado. Ordem: observação mais recente primeiro, depois fingerprint.

## Fingerprint

`SHA-256` (hex minúsculo de 64 caracteres) com prefixo de tamanho sobre `meufinanceiro:recurrence-suggestion:v1`, instalação, residência, conta, `EXPENSE`, moeda e descrição normalizada. **Não inclui** IDs de Movement nem datas: o feedback sobre a mesma assinatura sobrevive a novas observações. **Não é resource ID e não prova acesso**; o servidor sempre reexecuta o detector para o operador e só age sobre um fingerprint que ele produz agora. Uma forma inválida é `422`; um fingerprint que o operador não produz (inexistente, forjado, de outra conta/residência ou de conta invisível) é o mesmo `404`.

## Persistência (batch 2, migration `0027_recurrence_suggestions`)

Uma sugestão **nunca** é gravada. O que persiste é a decisão explícita do usuário em `finance.recurrence_suggestion_decisions`: `id` (UUID v4), `installation_id`, `residence_id`, `account_id`, `operator_id`, `currency`, `fingerprint` (64 hex), `decision` (`ACCEPTED` | `DISMISSED`), `recurrence_id` (somente `ACCEPTED`), `evidence_digest` (SHA-256 do que foi mostrado) e `decided_at`. CHECK de forma: `(decision = 'ACCEPTED') = (recurrence_id IS NOT NULL)`. FKs compostas com a residência, a conta (moeda), a membership do operador e a recorrência. Único por `(instalação, operador, fingerprint)` e por `recurrence_id`.

Garantias no banco:

- **append-only:** o runtime tem `SELECT` e `INSERT`, sem `UPDATE`, `DELETE` nem `TRUNCATE`; um gatilho `BEFORE UPDATE` recusa qualquer alteração, inclusive do papel privilegiado;
- **forma decidida pelo banco:** um gatilho `BEFORE INSERT` exige `decided_at` = instante da transação e, para `ACCEPTED`, uma recorrência **criada nesta mesma transação**, da mesma conta, moeda e `EXPENSE`, cujo dono é o operador da decisão: ninguém forja uma proveniência para uma recorrência antiga;
- **RLS `ENABLE` + `FORCE`:** leitura exige o escopo da residência (instalação, residência, membership ativa), visibilidade da **conta** sob a RLS da conta (PERSONAL, SHARED com grant, HOUSEHOLD) e, para `DISMISSED`, ser o próprio autor; `ACCEPTED` é proveniência de uma regra compartilhada e é legível por toda a audiência da conta. Inserção exige o próprio operador e, para `ACCEPTED`, conta ativa do dono e regra do dono;
- **unicidade como barreira de concorrência:** duas aceitações simultâneas não duplicam; a transação perdedora, inclusive a recorrência que ela inseriu, é desfeita;
- índice parcial `ix_finance_movements_expense_scan (residence_id, effective_date) WHERE role = 'STANDARD' AND result_effect = 'EXPENSE'` serve a varredura do detector; `finance.movements` não ganha coluna nem ponteiro.

## Store (`FinancialRecurrenceSuggestionStore`)

- **Leitura (`list_suggestions`)**: papel de runtime com RLS forçada, então um Movement invisível ao operador nunca entra no agrupamento. Quatro statements fixos (contexto, membership, varredura, regras) mais **um** de decisões quando há sugestão, nunca por linha, conta ou regra. Falha explícita (`FinancialRecurrenceSuggestionLimitError`) se a varredura passa de `SUGGESTION_SCAN_MAX` ou o resultado de `SUGGESTION_LIST_MAX`. Nada é escrito.
- **Dispensa (`dismiss`)**: idempotente (repetir devolve a decisão guardada), por operador, só para um fingerprint que o detector produz **agora** para ele; aceitar o que foi dispensado ou dispensar o que foi aceito é conflito.
- **Aceite (`accept`)**, tudo em uma transação: contexto e membership → replay de aceite anterior (mesma chave e mesmo material devolve a mesma recorrência, mesmo que a sugestão já tenha sumido) → decisão prévia → **reexecução do detector** → prova de dono → writer da #254 (`create_recurrence_in_transaction`, extraído de `create_recurrence` sem mudar seu comportamento) → decisão `ACCEPTED`. Qualquer falha desfaz recorrência, revisão 1 e decisão. Zero Movement e zero ocorrência.
- Erros próprios (todos sanitizados): `NotAvailable` (stale, forjado, já decidido, conta invisível ou outra residência, indistinguíveis), `NotEditable` (visível, mas só o dono aceita), `Conflict` (decisão incompatível), `Limit`; erros do writer da #254 passam como estão.

## API (batch 3)

Todas sob `/api/v1/finance`, autenticadas, na residência primária da sessão. Sem `PUT`, `PATCH` nem `DELETE`. Query params são `422`. O relógio é injetado no serviço (`clock`); a composição usa `date.today`.

| Método e rota | Efeito |
|---|---|
| `GET /recurrence-suggestions` | sugestões derivadas do operador; **nunca escreve**; `windowFrom`/`windowThrough` informam a janela de 12 meses |
| `POST /recurrence-suggestions/{fingerprint}/dismiss` | dispensa pessoal, idempotente (`200`, `created` diz se foi nova); sem corpo |
| `POST /recurrence-suggestions/{fingerprint}/accept` | cria **uma** recorrência canônica e a proveniência (`201`); corpo `{idempotencyKey, description, expectedAmount, startDate, dayOfMonth, endDate?}` |

Cada sugestão traz `fingerprint`, `accountId`, `description`, `normalizedDescription`, `currency`, `evidence` (`movementId`, `effectiveDate`, `amount`), `movementIds`, `observedDates`, `observedAmounts`, `suggestedDayOfMonth`, `suggestedExpectedAmount`, `amountBehavior` (`FIXED`/`VARIABLE`), `minAmount`, `maxAmount`, `lastAmount`, `reasonCodes` e `canAccept` (decidido no servidor: só o dono da conta aceita). Dinheiro é texto decimal.

O corpo do aceite tem `extra="forbid"`: **conta, efeito e moeda não existem no pedido**; vêm da sugestão que o servidor recalcula. Uma revisão malformada (descrição vazia, valor não positivo, dia fora de 1..31, término antes do início, chave inválida) é `422` e nada é gravado.

Erros públicos e sanitizados (sem SQL, constraint, fingerprint ou identificador):

| Situação | Resposta |
|---|---|
| sugestão que o operador não recebe agora (obsoleta, forjada, já decidida, conta invisível, outra residência) | `409` "no longer available": o cliente atualiza e decide de novo |
| decisão incompatível já gravada (aceitar o dispensado, dispensar o aceito, aceitar de novo com outra chave) | `409` conflito com decisão registrada |
| mesma chave com outro material | `409` conflito de idempotência |
| visível, mas não é dono da conta | `403` |
| fingerprint malformado, corpo inválido | `422` |
| varredura ou resultado no teto | `422` limite |
| sem membership | `403`; sem sessão `401`; indisponível `503` |

Retry idêntico do aceite (mesma chave e mesmo material) devolve `201` com a mesma recorrência e `decision.created = false`. Aceitações concorrentes, com a mesma chave ou com chaves diferentes, resultam em exatamente **uma** recorrência e **uma** decisão `ACCEPTED`; as demais recebem `409`.

## Smoke vertical

Provado por HTTP contra PostgreSQL 18.4 com role não-superusuário e RLS forçada (`test_smoke_the_issue_vertical_streaming_over_http`): *Streaming* de 39,90 em ago/set/out, mesma conta, uma por mês → `GET` sugere com evidências e motivos, saldo e extrato **inalterados** → o membro dispensa e a sugestão some só para ele (o dono ainda vê) → o dono revisa valor e dia e confirma → **exatamente 1** recorrência e a proveniência `ACCEPTED`, **zero** ocorrência e zero Movement novo, saldo e extrato inalterados → retry com a mesma chave não duplica, outra chave é `409` → a sugestão deixa de aparecer para todos.

## Limites

Janela fixa de 12 meses; a varredura lê no máximo `SUGGESTION_SCAN_MAX` = 20 000 Movements e a resposta traz no máximo `SUGGESTION_LIST_MAX` = 100 sugestões; ultrapassar qualquer um é erro explícito (nunca truncamento silencioso). Custo constante em statements.

## Pontos aceitos (P2), sem bloqueio

- a janela de dia fixa em ±3 dias é uma política conservadora e documentada, não uma estimativa de calendário bancário;
- o valor sugerido é o último observado, não uma mediana: é explicável e o usuário o revisa antes de confirmar;
- uma dispensa não expira quando surgem novas evidências;
- só despesas, só mensal, só contas ativas;
- uma recorrência equivalente criada manualmente ao mesmo tempo que um aceite pode coexistir com ele (equivalência é semântica de sugestão, não invariante do banco).

## Fora do escopo

Criação automática, detecção em segundo plano, ML/LLM/fuzzy, enriquecimento de merchant, metadados de provedor, receitas recorrentes assistidas, frequências semanal/anual/personalizada, cancelamento automático, alertas, comparação de preços, cobrança contestada, cartões e faturas, importação e conciliação, HML/PROD/deploy e GitHub Actions como gate.

## Estado do trabalho

| Batch | Escopo | Estado |
|---|---|---|
| 1 | domínio, detector puro, fingerprint, normalização e ADR-0028 | concluído |
| 2 | persistência de decisões, RLS, store do detector e writer transacional da recorrência | concluído |
| 3 | API accept/dismiss e concorrência (o writer transacional veio no batch 2) | concluído |
| 4 | Flutter, desempenho, smoke, docs e gates | pendente |
