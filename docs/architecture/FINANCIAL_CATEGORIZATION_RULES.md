# Regras determinísticas de categorização — API, persistência e Flutter

Status: **implementação completa da issue #247** (4 batches). Pull Request, merge e integração ao `develop` **ainda não ocorreram**.

Este documento descreve a capacidade entregue sobre a classificação append-only da #170/#245 (ADR-0022) e a auditoria da #171 (ADR-0023). As decisões estão na ADR-0024; nenhuma regra financeira anterior foi alterada.

## Contrato HTTP

Todos os endpoints são residence-scoped e audience-aware, sob `/api/v1/finance`, com erros sanitizados (`404`, `403`, `409`, `422`, `503`).

| Método | Caminho | Uso |
|---|---|---|
| `GET` | `/categorization-rules` | regras visíveis (ACTIVE primeiro, ordem determinística) |
| `POST` | `/categorization-rules` | cria uma regra imutável (`idempotencyKey` obrigatório) |
| `POST` | `/categorization-rules/{ruleId}/disable` | desabilita (somente o criador; replay seguro) |
| `POST` | `/accounts/{accountId}/categorization-rules/preview` | avaliação somente leitura da conta |
| `POST` | `/accounts/{accountId}/categorization-rules/apply` | aplicação explícita dos pares confirmados |
| `GET` | `/accounts/{accountId}/categorization-rules/origins` | proveniência bulk das classificações **correntes** |

Não existe `PUT`, `PATCH` ou `DELETE`, nem campo de regra em `finance.movements`. Os endpoints de classificação da #245 permanecem inalterados.

### Regra (v1)

```text
accountId        opcional, conta do operador, match exato
resultEffect     opcional, INCOME ou EXPENSE
descriptionMatcher  EXACT | CONTAINS
descriptionPattern  1..256 caracteres, sem controle (trim externo)
targetCategoryId ACTIVE e compatível com a audiência
priority         1..1000
```

Fora do recorte: regex, fuzzy, faixas de valor/data, merchant/provider, múltiplas categorias por regra e condições booleanas.

### Normalização e matching

`trim` de whitespace Unicode externo → NFC → `casefold` → NFC. Acentos, pontuação e espaçamento interno contam. `EXACT` compara tudo; `CONTAINS` testa substring. A função é única (`meufinanceiro_finance.categorization_rules`) e usada por preview e apply; o cliente não casa nada.

### Preview

Cada Movement da conta aparece em `items`, em ordem de ledger, com o seu próprio estado: `MATCHED` (exatamente uma regra vencedora), `NO_MATCH`, `AMBIGUOUS`, `INELIGIBLE` (`NEUTRAL`/`REVERSAL`) e `ALREADY_CLASSIFIED`. `ruleId` e `targetCategoryId` só existem em `MATCHED`, onde são semanticamente válidos. `counts` traz os cinco totais e `totalMovements`; `applicableTruncated` indica que mais de 200 Movements casaram (um apply carrega no máximo 200 pares: confirme os primeiros e pré-visualize de novo). Não há limite de detalhe: o preview tem o tamanho do extrato. Número constante de leituras (conta, Movements, classificações correntes, regras, categorias), independente do número de Movements. Nunca escreve, não toma lock e não garante o apply.

### Apply

Corpo: `{"items": [{"movementId", "ruleId"}, ...]}` (1..200 pares, sem Movement repetido). Uma transação por Movement; resposta por item:

| Status | Significado |
|---|---|
| `CLASSIFIED` | allocation set revisão 1 + proveniência + auditoria gravados |
| `ALREADY_CLASSIFIED` | já havia classificação (manual ou de regra): nada foi criado |
| `AMBIGUOUS` | empate na maior prioridade: nada foi criado |
| `NO_MATCH` | nenhuma regra utilizável casa agora |
| `INELIGIBLE` | `NEUTRAL`/`REVERSAL`, outra conta ou Movement inexistente/invisível |
| `CONFLICT` | o estado mudou (outra regra vence, regra/categoria mudou, escrita recusada): nada foi criado |
| `FAILED` | falha de persistência para aquele Movement: nada foi confirmado; o resto continua |

`200` com `requested`, contagens e resultados por item; só "tudo classificado" é sucesso total. Falhas de acesso/ownership abortam antes de qualquer escrita (`403`/`404`).

## Autoridade e invariantes

- `finance.movements` continua o único ledger; nada em Movement, saldo ou extrato muda (testado).
- `movement_allocation_sets` continua a única autoridade de classificação; a proveniência não é uma segunda.
- Backend/domínio/store decidem elegibilidade, audiência, ownership, concorrência, categoria, idempotência e persistência.
- Nenhum `float`/`double` é autoridade monetária; o share da regra reutiliza o Money exato do Movement (sinal preservado).
- Provider-neutral: nenhuma condição depende de payload Pluggy/Open Finance.

## Persistência (migration `0021_categorization_rules`)

| Tabela | Papel |
|---|---|
| `finance.categorization_rules` | regra residence-scoped; só `ACTIVE → DISABLED` muda (UPDATE de coluna + trigger); sem DELETE |
| `finance.movement_allocation_rule_origins` | proveniência 0..1 por allocation set; append-only; sem valores/descrição |

RLS habilitada e forçada em ambas. A regra só é visível se a categoria-alvo (e a conta) forem visíveis ao operador; somente o criador desabilita. Triggers de integridade: criação da regra (categoria ACTIVE, audiência, conta do criador), imutabilidade semântica e proveniência (revisão 1, regra ACTIVE travada `FOR SHARE`, condições, share único igual ao alvo e ao Money do Movement). `uq_finance_allocation_sets_origin_scope` foi adicionada às sets para a FK composta da origin. A migration é simétrica por downgrade.

## Concorrência e idempotência

- **Lock do conjunto de regras:** `create_rule`, `disable_rule` e `apply_rule_to_movement` adquirem o mesmo `pg_advisory_xact_lock`, namespace-específico e com escopo de residência (`categorization_rule_set_lock_key`, derivado de `(namespace, installation, residence)`; regras globais afetam qualquer conta, então um lock por conta não bastaria). O apply o adquire **antes** de ler regras e **antes** do lock de linha do Movement; criar/desabilitar só precisam dele. Assim o apply é linearizável contra qualquer mutação do conjunto: ou a regra maior/empatada commitou antes (o apply reavalia e devolve `CONFLICT`/`AMBIGUOUS`) ou o apply commitou antes (a regra só é criada depois). Preview e leituras não tomam o lock; a classificação manual continua serializada só pelo lock do Movement.
- O lock de linha do Movement (o mesmo da classificação manual) serializa regra × manual: exatamente uma classificação vence, sem revisão automática.
- Chave por Movement derivada de `(rule_id, movement_id)`; replay de apply nunca cria revisão.
- `disable` concorrente com apply se serializa pelo `FOR SHARE` da origin: ou a regra foi desabilitada antes (CONFLICT) ou a aplicação commitou antes.
- Se a proveniência falhar, allocation, shares e auditoria sofrem rollback juntos (testado).

## Auditoria

O lifecycle da regra **não** entra no audit financeiro fechado (`FinancialAuditEventDraft` inalterado; teste prova que não grava evento). A mutação financeira efetiva continua `ALLOCATION_SET_CREATED`, sem `rule_id` nem detalhe de matching. Cada origin corresponde a exatamente um evento auditado do operador que aplicou.

## Cliente Flutter

- Tela de regras (`/app/financas/regras`): listar, criar (EXACT/CONTAINS, conta e efeito opcionais, categoria ACTIVE compatível, prioridade) e desabilitar com confirmação. Sem edição e sem "desfazer regra".
- Detalhe da conta: *Aplicar regras* (somente dono de conta ACTIVE) abre preview somente leitura; *Confirmar e aplicar* envia os pares previstos uma única vez; o resumo exibido é o da resposta do backend, e qualquer resultado diferente de "todos classificados" aparece como **parcial**.
- Sem sucesso otimista: a regra criada só aparece após o `201`. Resultado ambíguo (timeout/5xx/2xx inválido) nunca é reenviado automaticamente: na criação há uma releitura única e o retry explícito idêntico reutiliza a chave; no apply o estado é "resultado desconhecido" e o operador pré-visualiza de novo.
- Após o apply, um refresh bulk (extrato, classificações e proveniência); linhas mostram *Aplicada por regra* somente se o allocation set **corrente** tem origin, então um override manual (#245) remove o rótulo. Nenhuma leitura por Movement.

## Pontos aceitos (P2), sem bloqueio

- Apply faz uma transação por Movement; para 200 pares são ~200 transações, cada uma relendo regras e categorias (poucas linhas). O lote é limitado de propósito para manter a requisição curta.
- A releitura de regras/categorias por Movement dentro do apply é intencional (revalidação canônica), não um N+1 de leitura de tela.
- A chave pendente de criação de regra vive no controller do Flutter; se a tela for fechada antes do retry explícito, uma nova tentativa gera nova chave (possível regra duplicada, que empata e falha fechado até uma ser desabilitada).
- Após reconciliação de um conflito de classificação manual (#245) o mapa de proveniência só é recarregado no próximo refresh completo; como a origin é indexada por allocation set, o pior efeito é a ausência do rótulo, nunca um rótulo errado.
- O lock do conjunto de regras é por residência: applies de contas diferentes da mesma residência, e criar/desabilitar regra, se serializam brevemente (cada apply é uma transação curta por Movement). É o recorte v1; um lock mais fino exigiria saber quais regras globais afetam qual conta.
- `FOR SHARE` na regra durante a aplicação permanece como segunda barreira (defesa em profundidade) para um `disable`.

## Fora do escopo desta entrega

ML/LLM, aprendizado, sugestão de regras, fuzzy/regex, condições arbitrárias, faixas de valor/data, regra com rateio, execução em background/agendada ou na importação, Pluggy/Open Finance, caixa de pendências (entregue depois pela #249; ver `FINANCIAL_PENDING_INBOX.md`), orçamento, recorrências, tags, classificação de `NEUTRAL`/`REVERSAL`, histórico visual completo de regras e HML/PROD/deploy.

## Evidência de fechamento

| Batch | Commit | Escopo |
|---|---|---|
| 1 | `5baebc8` | domínio, schema, migration `0021`, stores, RLS e proveniência |
| 2 | `f6efa59` | serviço e API: CRUD mínimo, preview, apply e leitura de origens |
| 3 | `0d9d2ec` | Flutter: regras, preview, confirmação, resumo real e refresh bulk |
| 4 | `b6810e8`, `87dc29b` | gate vertical, correção de lint do teste, hardening do parse do padrão e documentação |
| 5 | commit corretivo pré-PR | preview por Movement (todos os cinco estados) e lock transacional do conjunto de regras |

Gates executados localmente sobre `b6810e8` e reexecutados por completo sobre as correções do commit corretivo (mesmo resultado) (sem GitHub Actions, HML ou PROD), com PostgreSQL 18.4 descartável, role de runtime não-superuser sem `BYPASSRLS`:

- repository safety, DCO (`2f0c8df..HEAD`), `git diff --check`: PASS;
- `ruff check`, `ruff format --check`, `mypy --strict` (167 arquivos): PASS;
- Alembic com head único `0021_categorization_rules` e migration downgrade/re-upgrade: PASS;
- licenças Python, `pip-audit --local`: PASS;
- Flutter: toolchain, `pub get --enforce-lockfile`, licenças, `dart format`, suíte completa, build web, finalização e contrato PWA: PASS; `node --check`/teste do service worker: PASS;
- `flutter analyze` apontou um import não usado em um teste novo; corrigido no commit seguinte e reexecutado limpo (sem issues) junto com a suíte Flutter completa e `dart format`;
- suíte Python completa: **uma** falha, preexistente no `develop` e rastreada pela #240 (`tests/quality/test_safe_update_contract.py::test_update_contract_is_linked_and_ignored`), sem relação com esta issue — **PASS_WITH_PROVEN_BASELINE_EXCEPTION**.

Provas relevantes: manual vence a corrida preview→apply e applies concorrentes criam exatamente uma classificação; origin e allocation são atômicos (falha de proveniência reverte allocation e auditoria); `disable` concorrente se serializa com a aplicação (`FOR SHARE`); Movement, saldo e extrato idênticos antes/depois; preview sem escrita; leituras constantes para 0/1/N Movements; nenhum retry automático de escrita ambígua no Flutter. Os caminhos críticos foram verificados por mutação dirigida (26 mutantes no backend, serviço, lock e Flutter, todos detectados; dois mutantes equivalentes por redundância de validação foram descartados).
