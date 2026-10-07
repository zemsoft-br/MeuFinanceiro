# Recorrências mensais manuais — regra, ocorrência e realização explícita

Status: **em implementação (issue #254)**. Batches 1 a 3 de 4 concluídos: domínio, ADR, schema, RLS, versionamento, geração, skip, pause/resume, serviço, API e realização atômica. Pull Request, merge e integração ao `develop` **ainda não ocorreram**.

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

## Estado do trabalho

| Batch | Escopo | Estado |
|---|---|---|
| 1 | domínio, ADR-0027, schema, RLS, versionamento, criação/leitura/edição CAS com `SUPERSEDED` | concluído |
| 2 | geração, skip, pause/resume, serviço e API | concluído |
| 3 | realização atômica ligada ao Movement e concorrência | concluído |
| 4 | Flutter, smoke, desempenho, docs e gates | pendente |
