# ADR-0030 — Projetos como associação analítica auditável a despesas

- Status: Proposed
- Data: 2026-10-08
- Decisores: mantenedores
- Issue: #262; Epic: #180
- Base: develop@95c6fa754f8a6c77631c939f76419100fc800da1

## Contexto

A Fase 2 já possui um ledger único (ADR-0019/20), categorias com rateio
versionado (ADR-0022), orçamentos mensais derivados (ADR-0026) e metas com
destinação virtual de saldo (ADR-0029). Projetos são outra dimensão analítica:
uma reforma, viagem ou objetivo operacional pode agrupar despesas existentes
e ter um orçamento total próprio, sem qualquer transferência bancária.

## Decisão proposta

### Uma associação corrente por Movement original

- `finance.projects` persiste planejamento e CAS, mas não persiste realizado.
- `finance.project_movement_link_revisions` registra uma cadeia append-only
  **por Movement original**. A revisão inicial liga um projeto; sucessoras
  ligam outro projeto ou registram `project_id=NULL` para remover o vínculo.
- A chave do agregado é `movement_id`, **não** o projeto: o mesmo Movement
  jamais pode ter duas associações correntes entre projetos.
- `revision` é sequencial, `supersedes_id` aponta para predecessor e é
  único (sem forks); todo comando exige predecessor corrente explícito e
  `idempotencyKey` (UUIDv4) + SHA-256 do material canônico. Lock transacional
  por Movement protege a concorrência; atualização do ledger é proibida.
- Replay com mesma chave+digest retorna a revisão original mesmo depois de
  outras revisões, desde que autorizado; material diferente retorna 409.
- Acesso a histórico segue audiência do projeto e do Movement sem revelar
  projeto PERSONAL ou conta PERSONAL a visualizador HOUSEHOLD. Desvinculação
  de projeto pessoal não aparece como histórico sensível num projeto público.

### Contagem do realizado

- Só `STANDARD/EXPENSE` vincula; `INCOME`, `NEUTRAL`, e `REVERSAL`
  como alvos diretos são recusados.
- O valor realizado de cada vínculo corrente é `abs(original.amount)`.
  Se existir a reversão integral canônica, subtrair o valor revertido
  exatamente uma vez. A reversão segue o projeto **corrente** do original.
- A composição ocorre em leitura transacional consistente, sem cache de
  `realized_amount` ou alteração de `finance.movements`, saldo ou
  `finance.movement_allocations`.
- Orçamento total planejado do projeto é `Money` positivo; prazo opcional
  informativo e moeda imutável. Percentual derivado com HALF_UP em 2 casas.
  Uma meta da #260 não é um projeto e não reserva dinheiro aqui.

### Audiência e segurança v1

Projeto PERSONAL só aceita conta PERSONAL do mesmo owner; projeto HOUSEHOLD
só conta HOUSEHOLD do mesmo owner; SHARED fora. Owner da conta e do projeto
deve coincidir. Membros da residência leem projetos HOUSEHOLD mas somente
o owner altera. Novo LINK exige conta ACTIVE, remoção de vínculo histórico
pode operar com conta ARCHIVED. Runtime non-superuser, FORCE RLS, grants
mínimos e verificação SQL dos invariantes. Uma transição no status de
`finance.accounts` e a validação de INSERT de vínculo adquirem o mesmo
advisory lock transacional por `account_id`; assim o check de conta ACTIVE
não compete silenciosamente com um arquivamento por writer privilegiado.
A decisão não concede UPDATE em contas ao runtime. Não há segunda regra monetária
no Flutter.

### Estado de implementação

**Esta ADR é proposta no Batch 1**, ainda não autoriza uso em runtime. Antes
de ser Accepted, o Batch 2 precisa provar integridade, RLS e atomicidade de
links e reversões em PostgreSQL real; os Batches 3 e 4 acrescentam API e UX
com testes. A ausência desses gates bloqueia PR/merge.

## Alternativas rejeitadas

- Guardar `project_id` mutável em Movement: mistura analytics com ledger.
- Reutilizar categoria como projeto: mistura eixos e rompe rateio.
- Vínculo por projeto com ponteiro mutável corrente: permite dupla contagem.
- Link parcial entre vários projetos: adiado para uma child independente.
- Faturamento, marcos/tarefas e cronogramas automáticos: fora da v1.

## Validação necessária

Concorrência para mesmo Movement, CAS e idempotência sob corrida, ausência
de fork, LINK/UNLINK/reassign, auditoria de revisões, FX recusado,
PERSONAL/HOUSEHOLD e cross-residence, account archived, FULL REVERSAL,
zero segundo Movement, cache derivado ausente, RLS ENABLE/FORCE com runtime
NOSUPERUSER NOBYPASSRLS, desempenho bounded e Flutter/HTTP.

## Referências

#180, #245, #252, #260, #262; ADR-0019/20/22/23/26/29,
`docs/architecture/FINANCIAL_INVARIANTS.md` §11.2.
