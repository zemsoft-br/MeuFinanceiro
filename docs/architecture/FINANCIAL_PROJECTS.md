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

## Concorrência e replay

- A migration `0029_financial_projects` cria as tabelas, chaves
  estrangeiras compostas por âmbito, restrições, triggers e policies.
- `pg_advisory_xact_lock(hashtextextended('meufinanceiro:project-movement:' ||
  movement_id, 0))` serializa as mudanças de uma despesa. Tanto o
  store quanto o trigger usam a mesma chave.
- A transition de status em `finance.accounts` também usa lock
  transacional por conta (`meufinanceiro:project-account:{account_id}`),
  compartilhado com a validação de INSERT de vínculo no PostgreSQL.
  Isso ordena arquivamento privilegiado e nova associação, mesmo sem
  endpoint público de arquivamento; runtime mantém apenas SELECT/INSERT
  em contas. O trigger revalida `ACTIVE` depois do lock.
- Membro HOUSEHOLD com direito de leitura, mas não de escrita, recebe
  HTTP 403. Incompatibilidade de vínculo/CAS continua HTTP 409.
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
`financial_core_api.dart`. Ele valida corpos e respostas, identidades,
cadeia de revisões, limites e moeda. O controlador
`financial_project_controller.dart` reconcilia lista e resumo após
escritas, sem retry automático. A tela `financial_project_screen.dart`
e a rota `/app/financas/projetos` estão implementadas como candidato:
listagem, criação, edição e resumo do plano, incluindo leitura
`HOUSEHOLD` sem edição por membro. O detalhe apresenta descrição,
data e valores das despesas do ledger canônico, sem duplicar registros.
O extrato agora inclui uma ação sob demanda **Associar a projeto** para
despesas originais de contas PERSONAL/HOUSEHOLD do proprietário. O editor
`financial_project_link_dialog.dart` faz apenas duas leituras ao abrir
(projetos compatíveis e vínculo atual), permite associar, trocar,
desvincular (inclusive histórico de conta arquivada) e consultar
revisões auditáveis sob demanda. O comando leva `expectedPredecessorId`
e chave de idempotência; a tela reconcilia com GET mesmo após falha
ambígua, sem retries automáticos. Não existe leitura por linha do extrato.
**A implementação ainda não constitui aceite final**: exige Flutter
format/analyze/test/build e testes adversariais de integração.

## Evidências e pendências antes da PR

- Batch 1: 5 testes de domínio, Ruff e DCO PASS.
- Batch 2A: 3 testes de migration/RLS em PG18.4 PASS.
- Batch 2B: primeiro gate BLOQUEADO na limpeza da fixture
  append-only (não foi falha de operação do store).
- Correção de fixture publicada; **reexecução pendente**.
- Serviço/API, testes HTTP, tela Flutter e editor de vínculos publicados
  após o bloqueio, **todos pendentes de execução local**.
- O resumo usa pesquisa indexada por projeto e anti-join contra sucessor
  para localizar vínculos correntes, sem window-sort de toda a residência;
  exige EXPLAIN e stress com histórico amplo para comprovar boundedness.
- A regressão `A -> B -> A` valida realizado único após retorno ao
  projeto original, e testes do editor verificam leitura sob demanda e
  desvinculação de conta arquivada. **Ainda não executados.**
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

## Revalidação local em 2026-10-08

- Em `095245569c3e646266389725c1566fc6936aecf3`: 2.521 testes Python
  PASS e apenas a falha preexistente #240; 846 testes Flutter PASS;
  Ruff, mypy strict, RLS PostgreSQL 18.4, PWA, Web build, DCO, licenças e
  auditoria de dependências PASS. Exceção #240 verificada contra `develop`.
- Os commits **posteriores** de revisão adversarial introduzem correção da
  reconciliação do PUT Flutter, lock de transição de conta, HTTP 403 para
  escritor não proprietário, teste vertical HTTP→PostgreSQL e plano SQL
  `EXPLAIN ANALYZE` com 82 revisões. Essas alterações **ainda exigem gate
  local**; as evidências anteriores não as validam automaticamente.
- O plano SQL novo comprova indexabilidade e ausência de `WindowAgg`
  sobre histórico da residência. Não é benchmark de latência em produção:
  `enable_seqscan=off` é utilizado somente dentro da transação do teste.

## Fora do escopo

Rateio de despesas entre múltiplos projetos, fases, marcos,
tarefas, receita de projeto, câmbio, despesas futuras, SHARED,
regras bancárias/Pluggy, atualizações econômicas do Movement
e qualquer deploy/HML/PROD.
