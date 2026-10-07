# Recorrências mensais manuais — regra, ocorrência e realização explícita

Status: **em implementação (issue #254)**. Batch 1 de 4 concluído: domínio, ADR, schema, RLS e versionamento. Pull Request, merge e integração ao `develop` **ainda não ocorreram**.

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

## Estado do trabalho

| Batch | Escopo | Estado |
|---|---|---|
| 1 | domínio, ADR-0027, schema, RLS, versionamento, criação/leitura/edição CAS com `SUPERSEDED` | concluído |
| 2 | geração, skip, pause/resume, serviço e API | pendente |
| 3 | realização atômica ligada ao Movement e concorrência | pendente |
| 4 | Flutter, smoke, desempenho, docs e gates | pendente |
