# Projetos financeiros v1 — #262

> **Estado:** implementação em branch, **sem aceite de produção**.
> ADR-0030 ainda `Proposed`. Testes finais PostgreSQL/HTTP/Flutter
> e revisão adversarial são obrigatórios antes de criar PR.

## Objetivo

Agrupar despesas já existentes em projetos (ex.: reforma, viagem) e
comparar o orçamento **total** planejado ao realizado, sem alterar o ledger
nem tratar um projeto como categoria, orçamento mensal ou meta de saldo.

O plano contém `title`, `description`, `visibility_scope`,
`planned_amount` (`NUMERIC(24,8)`), moeda, prazo opcional e `version` CAS.
Moeda, residência, audiência e proprietário são identidade imutável.
O valor realizado não é persistido.

## Fonte monetária única

- `finance.movements` permanece o ledger e não ganha `project_id`.
- `finance.project_movement_link_revisions` contém uma **cadeia por
  Movement original**. `project_id` não nulo associa, nulo desvincula.
- Apenas `STANDARD/EXPENSE` de conta do mesmo owner, residência,
  audiência `PERSONAL/HOUSEHOLD` e moeda correspondente pode vincular.
  SHARED e rateio parcial entre projetos ficam fora da v1.
- `REVERSAL` integral acompanha o original; o agregado do projeto
  corrente subtrai a reversão exatamente uma vez, seja ela anterior
  ou posterior à associação.
- `INCOME`, `NEUTRAL`, receitas, transferências e saldos nunca
  aumentam o realizado. O valor realizado é sempre lido novamente.
- Orçamento mensal de categoria permanece independente: a mesma
  despesa pode ter categoria e projeto, sem duplicar o ledger.
- Leitura de resumo usa snapshot `REPEATABLE READ`; o store limita
  saída a 1000 despesas por projeto e 100 revisões por Movement,
  falhando sem truncar se ultrapassar o limite.

## Concorrrência e replay

- A migration `0029_financial_projects` cria as tabelas, chaves
  estrangeiras compostas por âmbito, restrições, triggers e policies.
- `pg_advisory_xact_lock(hashtextextended('meufinanceiro:project-movement:' ||
  movement_id, 0))` serializa as mudanças de uma despesa. Tanto o
  store quanto o trigger usam a mesma chave.
- O predecessor `supersedes_id` é CAS; `UNIQUE(supersedes_id)`
  impede forks, `UNIQUE(movement_id, revision)` impede números
  concorrentes duplicados.
- `idempotency_key` UUIDv4 e digest do material determinístico permitem
  replay idêntico; mesmo key com material diferente é conflito 409.
- Evento é append-only: INSERT permitido sob RLS; UPDATE/DELETE
  são rejeitados e runtime não possui TRUNCATE.
- A fixture de **PostgreSQL descartável** usa TRUNCATE privilegiado
  só para resetar as duas tabelas de testes. Não existe endpoint
  nem concessão de TRUNCATE em produção.
- A validação de permissão exige membership ativa; HOUSEHOLD
  pode ler como membro, mas apenas o owner edita.

## HTTP (candidato, sujeito aos gates)

| Método | Rota sob `/api/v1/finance` | Contrato |
|---|---|---|
| GET | `/projects` | Lista limitada, `canEdit` server-side |
| POST | `/projects` | Criar plano, `idempotencyKey` |
| GET | `/projects/{id}` | Plano |
| PUT | `/projects/{id}` | CAS `expectedVersion` |
| GET | `/projects/{id}/summary` | Realizado derivado, despesas atuais |
| GET | `/movements/{id}/project-link` | Associação corrente ou `null` |
| GET | `/movements/{id}/project-link/revisions` | Histórico completo e limitado |
| POST | `/movements/{id}/project-link` | Criar, trocar ou remover associação |

O POST de vínculo requer os três campos no corpo:
`idempotencyKey`, `projectId` (nullable) e
`expectedPredecessorId` (nullable). No primeiro LINK, predecessor é
`null`; nas revisões seguintes, corresponde exatamente ao id atual.
Desvincular exige `projectId=null` e predecessor não nulo.

Todas as quantias são strings decimais. Sem fields extras, ponto flutuante,
sucesso otimista, retries implícitos ou rebase automático de CAS.
Erros 401/403/404/409/422/503 sanitizados. Um Movement invisível
ou inexistente não deve parecer apenas "sem vínculo".

## Flutter (em implementação)

Cliente `financial_project_api.dart` foi incluído como `part` do
`financial_core_api.dart`. Ele valida os corpos e as respostas,
as identidades, a cadeia de revisões, limites e moeda. **Nenhuma tela
foi habilitada na navegação nesta etapa.** A interface deverá suportar
lista, criação/edição, resumo, associação/desvinculação a partir do
extrato, `HOUSEHOLD` read-only, conflitos, estados incertos e
reconciliação server-side após cada escrita.

## Evidências e pendências antes da PR

- Batch 1: 5 testes de domínio, Ruff e DCO PASS.
- Batch 2A: 3 testes de migration/RLS em PG18.4 PASS.
- Batch 2B: primeiro gate BLOQUEADO na limpeza da fixture
  append-only (não foi falha de operação do store).
- Correção de fixture publicada; **reexecução pendente**.
- Serviço/API, testes HTTP e cliente/testes Dart publicados após o
  bloqueio, **todos pendentes de execução local**.
- Pendente: testes adversariais completos de concorrência, digest/CAS,
  cross-residence, replay após troca, plano de desempenho FORCED RLS,
  mutação dirigida e Flutter UI/widget/build.
- Gates locais: safety, Ruff format/check, mypy strict, PG18.4
  não-superuser `NOBYPASSRLS`, alembic single head, pytest
  targeted/full, Flutter format/analyze/test/build, licenças,
  pip-audit, DCO e diff-check.
- Exceção histórica conhecida: #240, quando **única falha comprovada**,
  resulta em `PASS_WITH_PROVEN_BASELINE_EXCEPTION`. Não ignorar outras
  falhas nem executar GitHub Actions como gate.

## Fora do escopo

Rateio de despesas entre múltiplos projetos, fases, marcos,
tarefas, receita de projeto, câmbio, despesas futuras, SHARED,
regras bancárias/Pluggy, atualizações econômicas do Movement
e qualquer deploy/HML/PROD.
