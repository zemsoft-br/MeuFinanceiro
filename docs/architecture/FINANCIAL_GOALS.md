# Metas financeiras com destinação virtual (#260)

Status: **implementado (#260)** na branch `feat/financial-goals-260` (4 batches: domínio e ADR, persistência e concorrência, API, Flutter e documentação). Decisão: ADR-0029. Pull Request, merge e integração ao `develop` **ainda não ocorreram**.

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
| eventos por meta | 500 (475 para `ALLOCATE`; 25 ficam reservados para `RELEASE`, um por conta, para que uma meta no limite sempre consiga devolver tudo) |

Ao exceder, a escrita falha com `409`; um estado já fora do limite falha na leitura com `503` sanitizado, nunca cortado.

## Progresso e arredondamento

`progressPercent = destinado / alvo × 100`, `HALF_UP` em 2 casas, **sem teto** (pode passar de 100). `remainingTarget = max(alvo − destinado, 0)` e `surplus = max(destinado − alvo, 0)`. Estados: `NOT_STARTED`, `IN_PROGRESS`, `REACHED`, `EXCEEDED`. Reduzir o alvo abaixo do destinado resulta em `EXCEEDED`, sem ajuste automático.

## Prazo

Ao criar, ou ao alterar o prazo, a data deve estar entre `hoje(UTC) − 1 dia` e 100 anos à frente. Manter o prazo já gravado numa edição não revalida.

## Contrato HTTP

Residence-scoped sob `/api/v1/finance`. Erros sanitizados: `401`, `403` (acesso ou meta somente leitura), `404` (meta ou conta inexistente, invisível ou inelegível: o mesmo erro), `409`, `422`, `503`.

| Método | Caminho | Uso |
|---|---|---|
| `GET` | `/goals` | metas visíveis, cada uma com o destinado derivado (nenhum parâmetro é aceito) |
| `POST` | `/goals` | cria (`201`, replay-safe) |
| `GET` | `/goals/{id}` | lê |
| `PUT` | `/goals/{id}` | substitui os dados de planejamento sob `expectedVersion` |
| `GET` | `/goals/{id}/summary` | alvo, destinado, restante, progresso, contas com lastro e histórico |
| `POST` | `/goals/{id}/allocations` | `ALLOCATE` ou `RELEASE` (`201`, replay-safe) |

Não existe `DELETE` nem `PATCH`. Corpo desconhecido, ausente ou fora do contrato é `422` (o servidor nunca ignora um campo em silêncio).

- Criação: `idempotencyKey` (UUID v4), `title`, `description` (ou `null`), `visibilityScope` (`PERSONAL`/`HOUSEHOLD`), `currency`, `targetAmount`, `targetDate` (`YYYY-MM-DD` ou `null`). O dono e a residência vêm da sessão, nunca do corpo.
- Edição: `expectedVersion` (inteiro ≥ 1), `title`, `description`, `currency`, `targetAmount`, `targetDate`. Audiência, dono e moeda são imutáveis.
- Destinação: `idempotencyKey`, `operation` (`ALLOCATE` | `RELEASE`), `accountId`, `amount` (positivo) e `currency`. A resposta é o evento acrescentado (`id`, `goalId`, `accountId`, `operation`, `amount`, `actorOperatorId`, `createdAt`); o cliente lê o resumo de novo.
- Dinheiro é sempre texto decimal (`^(0|[1-9][0-9]{0,15})(\.[0-9]{1,8})?$`); `float`, `NaN`, notação científica e mais de 8 casas são `422`.

`409` distingue pelo texto sanitizado: `financial goal version is stale` (CAS), `financial goal allocation exceeds the available balance`, `financial goal release exceeds the allocated amount`, `financial goal limit reached` e `financial goal conflicts with canonical state` (chave reutilizada com outro material).

Resumo:

```text
goal { ..., target, targetDate, version, canEdit }
target, allocated, remainingTarget = max(target - allocated, 0), surplus = max(allocated - target, 0)
progressPercent (Decimal, 2 casas, meio para cima, sem teto), progressStatus NOT_STARTED | IN_PROGRESS | REACHED | EXCEEDED
hasInsufficientBacking
accounts[] { accountId, accountStatus, allocated, accountBalance, accountAllocatedTotal,
             backingStatus COVERED | INSUFFICIENT, shortfall }
events[] { id, goalId, accountId, operation, amount, actorOperatorId, createdAt }   # histórico completo, no máximo 500
```

`accountBalance` é o saldo canônico derivado da conta; `accountAllocatedTotal` é tudo o que **todas** as metas destinaram àquela conta. A insuficiência é da conta (não há atribuição entre metas e nenhum reequilíbrio). Como uma meta da casa só usa contas da casa, nenhum saldo de conta pessoal aparece para outro membro.

## Escrita e concorrência

| Cenário | Resultado provado |
|---|---|
| destinar duas vezes com a mesma chave e material | replay do mesmo evento, um só lançamento |
| mesma chave com outro material/meta/operador | `409`, nada gravado |
| 6 requisições simultâneas com a mesma chave | um evento |
| 8 metas disputando uma conta com saldo para 3 | exatamente 3 vencem, 5 `409`, soma ≤ saldo |
| 10 destinações simultâneas da mesma meta (saldo para 6) | exatamente 6 |
| 8 liberações simultâneas (cabem 2) | exatamente 2, nunca negativo |
| 5 a 6 edições simultâneas com a mesma versão | exatamente 1 vence |
| edição com versão antiga | `409`, nada gravado |
| liberar mais do que a meta tem na conta | `409` |
| conta arquivada | destinar é `404`; liberar funciona |
| Movement com o lock da conta segurado | Movement concluído sem esperar |

O mutante "sem lock por conta" é morto pelos testes de concorrência (10 destinações passam em vez de 6).

## Desempenho

O saldo é o canônico, lido por conta no mesmo statement de leitura do ledger (abertura + todos os Movements da conta). Logo, o custo **acompanha os Movements das contas envolvidas, nunca o tamanho do ledger inteiro**:

| Medição (PG 18.4, runtime não-superuser, RLS forçada) | Resultado |
|---|---|
| destinar numa conta com 20 mil Movements | ~0,85 s |
| destinar numa conta tranquila | ~0,03 s, inalterado depois de 60 mil Movements em outras contas |
| resumo com 25 contas / 50 mil Movements | ~1,9 s, 80 statements |
| listar metas (até 200 do dono) | ~9 ms |

O número de statements do resumo não segue eventos, Movements nem metas (só as 3 leituras por conta da meta, no máximo 25 contas); a lista tem um número fixo. Testes exigem os limites acima e a independência do número de statements.

## Cliente Flutter

Tela **Metas** (`/app/financas/metas`, atalho na lista de contas):

- lista de metas (título, audiência, moeda, barra de progresso e `destinado virtualmente X de Y`) e detalhe da meta selecionada;
- `Planejado (alvo)` versus `Destinado virtualmente`, `Falta para o alvo`, `Acima do alvo` quando houver, e o estado em texto (`Nada destinado ainda`, `Em andamento`, `Meta atingida`, `Acima do alvo`), nunca só por cor;
- aviso permanente `Destinação virtual; não transfere nem bloqueia dinheiro.` na tela, no diálogo de destinação e no de criação/edição, mais uma explicação de que despesas posteriores podem deixar a meta sem lastro e de que não há garantia bancária;
- criar/editar em diálogo (título, descrição, audiência, moeda, alvo, prazo); audiência e moeda não mudam depois de criadas; o prazo é validado no cliente só como espelho do contrato;
- `Destinar` e `Liberar` em diálogo com a lista de contas elegíveis (mesmo dono, mesma audiência, mesma moeda, ativas; `SHARED` nunca) ou, para liberar, as contas onde a meta tem valor (arquivadas incluídas);
- por conta: destinado à meta, saldo atual, total destinado em todas as metas e `Com lastro` / `Destinações acima do saldo` (com o quanto falta), mais um alerta geral quando houver insuficiência; histórico completo da meta;
- membro não-dono de uma meta da casa lê tudo e não vê `Editar`, `Destinar` nem `Liberar` (`canEdit` é do servidor);
- carregando, vazio, erro com tentar novamente, resumo indisponível/inválido (a meta continua visível), sessão expirada/sem acesso, estado possivelmente desatualizado e conflito.

Regras do cliente: sem `double` para dinheiro (a única conversão numérica é a fração da barra, por inteiros, a partir do texto do servidor), sem sucesso otimista, sem retry automático, sem refazer o CAS depois de um `409`, sem aritmética de destinado/restante/progresso/lastro. Toda escrita é enviada uma vez; qualquer resposta (sucesso, `409`, `403`, `404`, `422`, `5xx`, transporte, resposta inválida) termina em **uma** releitura canônica. Uma criação ou destinação de resultado desconhecido guarda a chave de idempotência só para uma repetição explícita e idêntica do usuário, que o servidor responde por replay. O custo é fixo: contas, metas e um resumo.

## Provas

- domínio: contratos, matriz de elegibilidade, disponibilidade, liberação, arredondamento do progresso, resumo e limites (`packages/finance/tests/test_goals.py`);
- persistência (PostgreSQL 18.4, role não-superuser, RLS forçada): CAS, idempotência, audiências, matriz de contas, concorrência, saldo que cai, estorno e transferência `NEUTRAL`, append-only, limites, ausência de Movement/orçamento/ocorrência/auditoria novos, equivalência do saldo transacional com o serviço canônico, migration e downgrade simétricos, custo (`packages/persistence/tests/test_financial_goals*.py`, `test_financial_goal_*.py`);
- API: vertical por HTTP, contrato estrito, saneamento, concorrência por HTTP e statements constantes (`apps/api/tests/test_financial_goals_*.py`);
- qualidade: contratos de domínio/persistência/API/Flutter (`tests/quality/test_financial_goal_contract.py`, `test_flutter_goal_contract.py`);
- Flutter: API, política, controller e tela (`apps/app/test/features/finance/financial_goal_*_test.dart`).

## Fora do escopo

Projetos/fases/marcos, vínculo de despesas ou classificação a metas, aposentadoria/investimentos, depósitos bancários reais, separação automática de contas, aporte agendado ou recorrente, metas em várias moedas ou com câmbio, `SHARED`, notificações, empréstimos, gráficos avançados, arquivamento/remoção de metas e deploy.
