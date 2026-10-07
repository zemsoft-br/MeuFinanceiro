# Recorrências mensais manuais — regra, ocorrência e realização explícita

Status: **implementação completa da issue #254** (4 batches) na branch `feat/finance-recurrences-254`. Pull Request, merge e integração ao `develop` **ainda não ocorreram**.

Normativo: ADR-0027. Este documento descreve o contrato, o schema e a API. Nenhuma regra financeira anterior foi alterada.

## Definição

Uma **recorrência** é um modelo mensal manual de receita ou despesa esperada. Uma **ocorrência** é a instância persistida desse modelo para um mês. **Nenhuma das duas é um fato financeiro**: só o `Movement` `STANDARD` é, e só depois de **Registrar** explícito. `PENDING`, `SKIPPED` e `SUPERSEDED` nunca alteram saldo nem extrato, e nenhum processo cria Movement sozinho.

## Schema (migration `0025_monthly_recurrences`)

`finance.recurrences` (regra): `id` (UUID v4), `installation_id`, `residence_id`, `account_id`, `owner_operator_id`, `description`, `result_effect` (`INCOME`/`EXPENSE`), `currency`, `expected_amount` `NUMERIC(24,8) > 0`, `frequency = 'MONTHLY'`, `start_date`, `day_of_month` 1..31, `end_date`, `status` (`ACTIVE`/`PAUSED`), `version`, `idempotency_key`, `request_digest`, `updated_by_operator_id`, timestamps. FK composta com a conta garante a moeda; identidade imutável por gatilho; versão avança de um em um.

`finance.recurrence_occurrences` (instância): UUID v4, regra, conta, dono, `period_start` (primeiro dia do mês), `scheduled_date`, `rule_version` e o snapshot (efeito, moeda, valor esperado, descrição), `status` (`PENDING`/`REALIZED`/`SKIPPED`/`SUPERSEDED`), `movement_id` (único, só quando `REALIZED`), chave e digest da realização, quem e quando realizou, `skipped_at`, `superseded_at`. Índice único parcial por `(recurrence_id, period_start)` onde `status <> 'SUPERSEDED'`.

Garantias no banco, além do store:

- gatilho de inserção: a ocorrência copia a revisão **corrente** da regra, a regra tem de estar `ACTIVE` (uma regra `PAUSED` não recebe ocorrência nem por SQL direto), a data é a que o calendário mensal produz entre `start_date` e `end_date`, e a conta está ativa;
- gatilho de transição: só `PENDING` se move, só para `REALIZED`/`SKIPPED`/`SUPERSEDED`, só as colunas de marca mudam; `REALIZED` exige um Movement `STANDARD` da mesma conta, efeito e moeda criado **na mesma transação** pelo mesmo operador;
- RLS `ENABLE` + `FORCE`; leitura segue a audiência da conta (política consulta `finance.accounts` sob a RLS da conta); inserção e atualização só do dono; o runtime tem `SELECT`, `INSERT` e `UPDATE` de colunas explícitas, **sem `DELETE` nem `TRUNCATE`**;
- `finance.movements` não muda.

## Calendário

Função pura de `date` (`monthly_occurrence_date`): dia 31 → 28/29 em fevereiro, 30 em abril; ano bissexto e séculos (2100 não é bissexto, 2000 é). `start_date` e `end_date` são inclusivos e comparam com a **data agendada**. Janela de geração: no máximo 12 meses por chamada e nunca além de 24 meses depois do mês de hoje (relógio injetado). Janela de leitura: no máximo 12 meses.

## API (batch 2)

Todas sob `/api/v1/finance`, autenticadas, na residência primária da sessão. Sem `DELETE` nem `PATCH`. Query params desconhecidos são `422`.

| Método e rota | Efeito |
|---|---|
| `GET /recurrences[?status=ACTIVE\|PAUSED]` | regras visíveis (audiência da conta), teto de 200 |
| `POST /recurrences` | cria; `idempotencyKey` obrigatório, replay-safe; conta própria, ativa e na moeda |
| `GET /recurrences/{id}` | uma regra (`canEdit` decidido no servidor) |
| `PUT /recurrences/{id}` | edita descrição, valor esperado, dia e término com `expectedVersion`; resposta traz `supersededCount` |
| `POST /recurrences/{id}/pause` · `resume` | idempotentes por estado; pausar não altera ocorrências; retomar não gera |
| `POST /recurrences/{id}/occurrences/generate` | `{fromPeriod, throughPeriod}` (`YYYY-MM`), no máximo 12 meses e 24 meses de horizonte; devolve `createdCount` e as ocorrências vivas da janela |
| `GET /recurrence-occurrences?fromPeriod&throughPeriod[&recurrenceId][&status]` | janela de até 12 meses; `SUPERSEDED` só com `status=SUPERSEDED` |
| `POST /recurrence-occurrences/{id}/skip` | `PENDING → SKIPPED`, idempotente |
| `POST /recurrence-occurrences/{id}/realize` | **Registrar**: um Movement `STANDARD` canônico ligado atomicamente (ver abaixo) |

Erros públicos e sanitizados: `404` recurso/conta inexistente ou invisível (indistinguíveis), `403` sem permissão de escrita, `409` versão antiga / regra pausada / estado da ocorrência / conflito de idempotência, `422` pedido inválido, `503` indisponível. Nenhuma resposta vaza SQL, nome de constraint ou identificadores.

O relógio é injetado no serviço (`clock: Callable[[], date]`); a composição da aplicação usa `date.today`. Ele define o horizonte da geração e o limite "futuro" da edição, nada mais.

## Realização (batch 3)

`POST /finance/recurrence-occurrences/{id}/realize` com `{idempotencyKey, actualAmount, currency, effectiveDate, competenceDate}` (todos obrigatórios; `actualAmount > 0`; a moeda precisa ser a da ocorrência). O valor real pode diferir do esperado; a regra não muda. Resposta `200` com a ocorrência `REALIZED` e `realization` (`movementId`, `actual`, datas, `realizedAt`, `movementState`).

**Atomicidade.** `FinancialMovementStore.create_movement` virou um invólucro de transação sobre `create_standard_movement_in_transaction(connection, …)`, o mesmo corpo, sem mudança de comportamento. A realização chama essa função na **própria transação** e, em seguida, liga a ocorrência (`PENDING → REALIZED` com `movement_id`). Uma única transação: ou existem o Movement (com seu audit `MOVEMENT_CREATED`) e o vínculo, ou nenhum dos dois. Ordem: contexto e membership → trava da ocorrência → replay → revalidação (ocorrência `PENDING`, regra, conta ativa do dono, moeda, residência) → Movement → vínculo. O gatilho do banco só aceita `REALIZED` com um Movement `STANDARD` da mesma conta, efeito e moeda criado nesta transação pelo mesmo operador; `movement_id` é `UNIQUE`.

| Situação | Resultado |
|---|---|
| mesma chave e mesmo material | converge: mesma ocorrência, mesmo Movement, nada novo |
| mesma chave, outro material ou outra ocorrência | `409` conflito de idempotência |
| outra chave sobre ocorrência já realizada | `409` estado |
| `SKIPPED` / `SUPERSEDED` | `409` estado |
| conta inativa, de outro dono ou outra moeda | `404` conta |
| data efetiva anterior ao saldo inicial | `422` (nada persiste) |
| membro sem posse | `403`; oculta ou de outra residência `404` |
| concorrência | trava da ocorrência serializa; um vencedor, nunca dois Movements |
| estorno do Movement | a ocorrência continua `REALIZED`; `movementState = REVERSED`; nada é reaberto, regenerado ou criado |

A chave de realização não é a chave de idempotência do Movement (esta é gerada na transação), para que uma chave de realização nunca adote um Movement avulso já existente. Registrar **nunca classifica**: o Movement nasce sem allocation e segue os fluxos #245/#247/#249.

Uma regra `PAUSED` não impede registrar uma ocorrência `PENDING` que já existe: pausar impede *gerar*, não encerra o que foi previsto.

## Limites explícitos

Uma lista nunca é cortada em silêncio. Um visualizador enxerga no máximo **200 regras** (`RECURRENCE_LIST_MAX`): criar além disso é `422 financial recurrence limit reached`. Uma janela de ocorrências tem no máximo **200 × 12 = 2400** linhas (uma viva por regra e mês); se um conjunto ultrapassasse o teto, a leitura falha com o mesmo `422` em vez de devolver parte. Geração: 12 meses por chamada, 24 meses de horizonte. Leitura: janela de 12 meses.

## Cliente Flutter

Tela **Recorrências** (`/app/financas/recorrencias`, atalho em Finanças):

- aviso fixo e em texto: *previsto não altera o saldo nem o extrato; somente Registrar cria um lançamento*;
- regras **Ativas** e **Pausadas** (descrição, tipo, esperado, dia — com a nota de que dia inexistente cai no último dia do mês —, início/término, conta, status, somente leitura quando não é dono);
- criar e editar (conta própria e ativa, tipo, valor esperado, descrição, dia, término); na edição, conta, tipo, moeda e início são imutáveis e o diálogo explica que previsões futuras incompatíveis serão substituídas;
- lista do mês navegável com `PENDING` (**Prevista**), `REALIZED` (**Registrada**) e `SKIPPED` (**Pulada**): o status é sempre dito em texto e com a dica do efeito no ledger; para registradas mostra **previsto × real**, datas e o estado do lançamento (`ACTIVE`/`REVERSED`, sem reabrir);
- **Gerar {mês}** explícito por regra ativa; **Registrar** (valor real, data efetiva e de competência, pré-preenchidos com a previsão mas sempre confirmados) e **Pular** (pede confirmação); **Pausar/Retomar**;
- estados de carregamento, vazio, erro (com Tentar novamente explícito), sessão/acesso, resposta inválida, somente leitura e conflito.

Contratos do cliente (provados por testes e pelo contrato de qualidade):

- **sem sucesso otimista:** após qualquer resposta de escrita (sucesso, 409, 403, 404, 422, 5xx, transporte, 2xx inválido) a tela é lida de novo uma vez e só isso muda o estado;
- **sem retry automático:** uma escrita é enviada uma vez; resultado incerto mantém a chave de idempotência **só** para um retry idêntico e explícito do usuário (o servidor converge) e a mensagem diz que nada será reenviado;
- um `409` nunca é reaplicado nem rebaseado: a tela mostra o estado atual e exige nova ação;
- custo fixo por tela: contas, regras e um mês de ocorrências (3 requisições), nunca uma por regra ou ocorrência; sem `double` para dinheiro, sem calendário nem saldo no cliente.

## Smoke vertical

Provado por HTTP contra PostgreSQL 18.4 com role não-superusuário e RLS forçada (`test_smoke_the_issue_vertical_internet_expense_over_http`): regra mensal *Internet*, `EXPENSE`, esperado 120, dia 10 → gera outubro `PENDING` → saldo e extrato **inalterados** → registrar 127.50 com datas explícitas → **exatamente 1 Movement** `EXPENSE` de −127.50, ocorrência `REALIZED` ligada, saldo 872.50 → retry idêntico **não duplica** → gera novembro → pausa → dezembro **não gera** (`409`) → retoma → gera dezembro → pula → **nenhum Movement** de dezembro. A mesma narrativa está nos testes do store e no teste Flutter com backend falso.

## Desempenho

`test_financial_recurrence_performance.py`: o número de statements por chamada é constante para 1 ou 61 regras, para gerar 1 ou 12 meses (um único `INSERT` para a janela) e ler realizadas acrescenta exatamente 2 statements por página (Movements e estornos), nunca um por linha; com 200 regras × 12 meses (2400 ocorrências) a leitura da janela e das regras ficou em ~0,7 s sob RLS forçada (teto de 5 s só contra plano descontrolado) e as consultas de janela e de "futuras pendentes" são servidas por índices (`ix_finance_recurrence_occurrences_period/_rule/_pending`).

## Pontos aceitos (P2), sem bloqueio

- sem paginação além dos tetos acima: o produto prefere recusar a esconder linhas; paginação por cursor fica para quando o uso real pedir;
- sem auditoria de ciclo de vida da regra em `finance.audit_events` (como orçamentos): a criação do Movement continua auditada pelo writer canônico;
- `pause/resume` não usam CAS: são comandos de estado alvo, idempotentes;
- o relógio de produção é `date.today` (composição da aplicação); o domínio e o store não leem relógio;
- a tela lista um mês por vez: uma previsão vencida e ainda `PENDING` de um mês anterior aparece ao navegar até aquele mês (não há fila agregada de vencidas na v1);
- registrar uma ocorrência de regra pausada é permitido: pausar impede gerar, não encerra a previsão existente.

## Fora do escopo desta entrega

Outras frequências, assinaturas assistidas e detecção automática, classificação automática, pagamentos parciais, cartões e faturas, transferências recorrentes, valor variável inferido, reajuste automático, alertas e notificações, fluxo de caixa e cenários, importadores e Pluggy, HML/PROD/deploy e GitHub Actions como gate.

## Evidência de fechamento

Validação local (PostgreSQL 18.4 descartável, role não-superusuário, RLS forçada; sem GitHub Actions):

| Gate | Resultado |
|---|---|
| segurança do repositório, `git diff --check`, DCO | passou |
| ruff (check e format), mypy `--strict` | passou |
| Alembic | head único `0025_monthly_recurrences`; upgrade/downgrade simétricos |
| pytest completo (finance, banking, security, persistence, API, worker, qualidade) | 2122+ passaram; **1 falha, o baseline #240** (`test_update_contract_is_linked_and_ignored`) |
| Flutter | format, analyze (sem issues), 703 testes, build web release e contrato PWA |
| licenças Python e Flutter, pip-audit | passou, sem vulnerabilidades conhecidas |
| mutação dirigida (36 mutantes: calendário, máquina de estados, CAS, idempotência, atomicidade, gatilhos, RLS, serviço) | 35 mortos; 1 sobrevivente equivalente (abaixo) |

Mutante sobrevivente, aceito: remover o `SELECT … FOR UPDATE` explícito da regra em geração/edição/pausa não altera a segurança, porque a FK da ocorrência (`FOR KEY SHARE`), o CAS do `UPDATE` e o gatilho de inserção (que relê a regra) já serializam ou recusam o mesmo cenário; o lock explícito troca um erro raro por espera. Os locks de **ocorrência** (skip/registrar) são provados por teste de bloqueio.

A mutação encontrou três lacunas reais de teste, todas fechadas: fronteira "hoje" da edição (domínio e SQL), chave de realização adotando um Movement preexistente e unicidade do vínculo Movement→ocorrência.

## Estado do trabalho

| Batch | Escopo | Estado |
|---|---|---|
| 1 | domínio, ADR-0027, schema, RLS, versionamento, criação/leitura/edição CAS com `SUPERSEDED` | concluído |
| 2 | geração, skip, pause/resume, serviço e API | concluído |
| 3 | realização atômica ligada ao Movement e concorrência | concluído |
| 4 | Flutter, smoke, desempenho, docs e gates | concluído |
