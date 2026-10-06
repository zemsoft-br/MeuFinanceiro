# Caixa de pendências de classificação — API, desempenho e Flutter

Status: **implementação completa da issue #249** (4 batches). Integrada ao `develop` pela PR #250 e consolidada em `main` pela PR #251.

Este documento descreve a caixa de pendências v1 sobre a classificação append-only da #170/#245 (ADR-0022), a auditoria da #171 (ADR-0023) e as regras determinísticas da #247 (ADR-0024). A decisão está na ADR-0025; nenhuma regra financeira anterior foi alterada.

## Definição

Uma pendência é **derivada** em cada leitura, nunca persistida:

```text
role = STANDARD
result_effect IN (INCOME, EXPENSE)
sem movement_allocation_set
visível ao operador (RLS forçada)
```

Não há tabela, fila, coluna de status, `category_id` ou `inbox_status`. `NEUTRAL` e `REVERSAL` ficam fora. Classificar (manualmente, por regra ou concorrentemente) remove o item na leitura seguinte; a caixa não pode divergir do ledger. A caixa nunca altera Movement, saldo ou extrato (testado).

## Contrato HTTP

`GET /api/v1/finance/pending-movements` — residence-scoped, audience-aware, somente leitura. Não existe `POST`, `PUT`, `PATCH` ou `DELETE` (405) e nenhum outro caminho de caixa. Erros sanitizados: `401`, `403`, `404` (conta inexistente ou invisível), `422` (parâmetro inválido), `503`. Resposta com `Cache-Control: no-store`.

| Parâmetro | Regra |
|---|---|
| `limit` | 1 a 100, padrão 50 |
| `cursor` | opaco, ≤ 256 caracteres `[A-Za-z0-9_-]`, preso ao conjunto de filtros |
| `accountId` | opcional, conta visível (senão `404`) |
| `resultEffect` | opcional, `INCOME` ou `EXPENSE` |
| `ruleStatus` | opcional, `MATCHED`, `AMBIGUOUS` ou `NO_MATCH` |

`offset`, `page`, `search` e qualquer outro parâmetro são recusados com `422`.

```text
{ "items": [ ... ], "nextCursor": string | null }
```

Item:

```text
movementId, accountId
money { amount (decimal em texto), currency }
resultEffect, effectiveDate, competenceDate, description
accountVisibilityScope, accountOwnerOperatorId
canClassify
ruleStatus: MATCHED | AMBIGUOUS | NO_MATCH
matchedRuleId?        # somente MATCHED
suggestedCategoryId?  # somente MATCHED
```

Dinheiro é texto decimal; nunca `float`/`double`. Nada específico de provider aparece.

## Paginação

Ordem determinística `effective_date DESC, id DESC` e posição keyset `(effective_date, id)`. O cursor é versionado, estrito (JSON canônico em base64 URL-safe, sem preenchimento), carrega só a coordenada e a impressão digital dos filtros, e falha fechado em qualquer malformação ou reutilização sob outros filtros (`422`). **Não é autorização**: a RLS decide o que cada leitura enxerga. `nextCursor` é `null` apenas quando não há mais candidatos.

Páginas não repetem nem perdem itens quando Movements são criados ou classificados entre leituras (provado com inserções mais novas e mais antigas que o cursor e com classificação entre páginas).

### Filtro por regra e orçamento de varredura

`accountId` e `resultEffect` são filtros SQL. `ruleStatus` depende do matching, que existe só no domínio (#247), então o serviço varre lotes keyset de 100 candidatos, avalia e filtra, com **no máximo 5 lotes** por requisição. Se a página enche, o cursor retoma logo após o último item devolvido (o restante do lote é revarrido, nada é pulado). Se o orçamento acaba antes, a resposta traz os itens que casaram até ali (possivelmente nenhum) **e um cursor**: a página pode ser curta, nunca ilimitada, e o cliente segue o cursor.

## Avaliação de regras

Exatamente o pipeline da #247, uma vez por conta (não por Movement): regras `ACTIVE` da conta, descarte das cujo alvo está ausente, `DISABLED` ou incompatível com a audiência da conta, maior prioridade única vence, empate é `AMBIGUOUS` e nada desempata. Regra ou categoria desabilitada muda o estado derivado na leitura seguinte. Um teste de equivalência prova que, para a mesma conta, a caixa e o preview concordam em estado, regra e categoria. Para um item de conta de outro membro (`canClassify=false`) a sugestão usa as regras que a RLS mostra ao operador e é informativa.

## Desempenho

Custo por requisição (provado por contagem de statements, independente de Movements, contas, allocations, regras e categorias):

| Leitura | Statements |
|---|---|
| sem filtro de regra | 9 = regras (3) + categorias (3) + página (3) |
| com `accountId` | + 1 verificação da conta |
| com `ruleStatus` | 6 fixos + até 3 por lote, no máximo 5 lotes |

Nenhuma consulta por linha de conta, allocation, regra ou categoria. No Flutter, a carga é 1 página + categorias + contas, sem requisição por linha.

A consulta limita e ordena os Movements **antes** de juntar contas, para caminhar um índice parcial e parar após `limit + 1` linhas. A migration `0022_pending_movement_indexes` cria dois índices parciais apenas de desempenho (sem tabela, coluna, grant, policy ou trigger; simétrica por downgrade):

```text
ix_finance_movements_pending_scan          (residence_id, effective_date DESC, id DESC)
ix_finance_movements_pending_account_scan  (residence_id, account_id, effective_date DESC, id DESC)
WHERE role = 'STANDARD' AND result_effect IN ('INCOME', 'EXPENSE')
```

Medição local (PostgreSQL 18.4, role não-superuser, RLS forçada, 60 mil Movements, 70% classificados), primeira página de 50:

| Estratégia | Tempo | Buffers |
|---|---|---|
| junta contas antes de limitar, sem índice | ~4,2 s | ~445 mil |
| junta contas antes de limitar, com índice | ~0,7 s | ~494 mil |
| limita primeiro + índices parciais | ~5 ms | ~2,3 mil |

Um teste automatizado exige que o plano use o índice parcial, não faça varredura sequencial de `movements` e percorra menos de 1.000 entradas para uma página de 50 em uma residência de 30 mil Movements.

## Autorização

- Ator e residência vêm do servidor; a RLS permanece forçada e fail-closed.
- `canClassify` = o operador é dono de uma conta `ACTIVE` (a autoridade de escrita da classificação manual e do apply). Um item visível pode ser somente leitura (conta de outro membro ou arquivada); a UI não oferece mutação enganosa.
- Operador de outra residência ou sem membership recebe `403`; contas invisíveis e inexistentes são indistinguíveis (`404`).
- Conhecer um `movementId`, `ruleId` ou `categoryId` nunca prova autorização.

## Cliente Flutter

Tela **Pendências** (`/app/financas/pendencias`, acessível pela lista de contas):

- estados de carregamento, vazio, vazio com filtro, erro com nova tentativa manual, acesso indisponível e lista possivelmente desatualizada;
- filtros por conta, tipo e sugestão, sempre refletindo a lista exibida;
- badges `Sugestão encontrada`, `Ambígua` e `Sem sugestão`; categoria sugerida visível em `MATCHED`; descrição, data, valor e conta legíveis, sem ids internos;
- paginação keyset com **Carregar mais** explícito (a tela vive dentro de um scroll não-lazy do shell, então não há gatilho de rolagem), sem repetir linhas e mantendo as já carregadas em caso de falha;
- `Aplicar sugestão` somente em `MATCHED` e só após diálogo de confirmação; `AMBIGUOUS` nunca escolhe regra e só oferece `Classificar`;
- `Classificar` reutiliza o endpoint da #245 e a política de categorias (uma categoria, valor exato do Movement); ratear entre categorias continua na tela da conta (atalho no diálogo);
- itens somente leitura mostram o motivo e nenhuma ação.

### Sem sucesso otimista, sem retry automático

Nenhum item sai antes de uma releitura canônica. Toda resposta de escrita (sucesso, `CLASSIFIED`, `ALREADY_CLASSIFIED`, `CONFLICT`, `AMBIGUOUS`, `NO_MATCH`, `FAILED`, `409`, `404`, `422`, 5xx, transporte ou 2xx inválido) termina em **uma** releitura da primeira página e das categorias, que substitui a lista. A mensagem diz o que o servidor confirmou (ou que nada foi gravado). Se a releitura falha, o item permanece, a lista é marcada como possivelmente desatualizada e novas escritas ficam bloqueadas até *Atualizar*. Resultado desconhecido nunca é reenviado; o retry explícito e idêntico da classificação manual reutiliza a chave de idempotência (a tentativa lógica é Movement + categoria). Uma escrita nunca começa durante o carregamento de uma página nem enquanto outra está em andamento.

## Concorrência

| Cenário | Resultado provado |
|---|---|
| classificação manual entre listagem e apply | apply devolve `ALREADY_CLASSIFIED`; a caixa não recria a pendência; um único allocation set |
| regra desabilitada antes do apply | `NO_MATCH`; nada gravado; a caixa passa a `NO_MATCH` |
| regra mais forte criada antes do apply | `CONFLICT`; a caixa passa a `MATCHED` com a nova regra |
| regra equivalente criada antes do apply | `AMBIGUOUS`; nada gravado; sem regra na caixa |
| apply × classificação manual em paralelo | exatamente um vencedor por Movement |
| leituras durante escritas | sem bloqueio nem alteração |

## Autoridade e invariantes

- `finance.movements` continua o único ledger; `movement_allocation_sets` continua a única autoridade de classificação; as regras são apenas sugestão explicável.
- Nenhum estado de caixa em banco (testado em `information_schema`), nenhum `float`/`double`, nenhuma semântica de provider.
- A caixa e o Flutter não decidem regra financeira: elegibilidade, prioridade, audiência, ownership e concorrência são do backend.

## Pontos aceitos (P2), sem bloqueio

- Com `ruleStatus`, a página pode vir curta ou vazia com cursor (orçamento de varredura fixo).
- Movements de contas arquivadas e `STANDARD` estornados ainda não classificados continuam listados, somente leitura quando aplicável.
- Em residências quase totalmente classificadas a varredura do índice avança mais antes de achar `limit` pendências; permanece limitada pelo orçamento e por índice, sem consulta por linha.
- A sugestão de um item de conta alheia usa as regras visíveis ao operador e pode diferir da do dono.
- A migration `0022` cria índices sem `CONCURRENTLY` (bloqueia escritas em `movements` durante a criação, aceitável em instalação local).
- A v1 não tem seleção múltipla nem aplicação em lote; o apply é uma sugestão por vez.
- A releitura após uma escrita volta à primeira página; quem estava em páginas mais fundas continua com **Carregar mais**.
- O diálogo de classificação não cria categorias nem rateia; ambos continuam na tela da conta.

## Fora do escopo desta entrega

Estado persistido de dismiss/snooze, atribuição de pendência a membro, ML/LLM e aprendizado, criação automática de regra, auto-apply, execução em background, tags, orçamentos (entregues depois pela #252; ver `FINANCIAL_BUDGETS.md`), recorrências, dashboard, importação/Pluggy, classificação de `NEUTRAL`/`REVERSAL` e HML/PROD/deploy.

## Evidência de fechamento

| Batch | Commit | Escopo |
|---|---|---|
| 1 | `13d706e` | read model, store keyset, migration `0022`, PostgreSQL/RLS/desempenho |
| 2 | `0679911` | serviço, rota, cursor, filtros e avaliação da #247 |
| 3 | `8da1c61` | Flutter: tela, controller, API, reuso dos fluxos #245/#247 |
| 4 | commit deste documento | concorrência, smoke vertical, contratos, documentação e gates |

Os resultados dos gates finais do Batch 4 constam do relatório de fechamento da issue.
