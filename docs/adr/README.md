# Architecture Decision Records

ADRs registram decisões estruturais, contexto, alternativas e consequências.

## Decisões vigentes

- [ADR-0002 — Fonte local de verdade e adaptadores](0002-local-source-of-truth-and-adapters.md)
- [ADR-0003 — GitFlow e colaboração orientada a issues](0003-gitflow-and-issue-driven-collaboration.md)
- [ADR-0004 — Licença, contribuições e política de marca](0004-project-license-and-trademark.md)
- [ADR-0005 — Configuração segura, criptografia e gerenciamento de chaves](0005-security-configuration-and-key-management.md)
- [ADR-0006 — Persistência e fila de tarefas no PostgreSQL](0006-postgresql-persistence-and-task-queue.md)
- [ADR-0008 — Flutter como cliente canônico multiplataforma](0008-flutter-multiplatform-client.md)
- [ADR-0012 — Persistência, segurança e feature flag da integração bancária](0012-banking-integration-persistence-security-and-feature-flag.md)
- [ADR-0013 — Autenticação local de operador e sessões opacas](0013-local-operator-authentication.md)
- [ADR-0014 — Residência primária derivada da associação do operador](0014-primary-residence-context.md)
- [ADR-0015 — Representação monetária e arredondamento canônicos](0015-canonical-money-representation-and-rounding.md)
- [ADR-0016 — Visibilidade e autorização de recursos financeiros](0016-financial-resource-visibility-and-authorization.md)
- [ADR-0017 — Identificadores canônicos de recursos financeiros](0017-canonical-financial-resource-identifiers.md)
- [ADR-0018 — Saldo de abertura imutável por conta](0018-immutable-account-opening-balance.md)
- [ADR-0019 — Movement canônico e ledger append-only](0019-canonical-movement-append-only-ledger.md)
- [ADR-0020 — Persistência de Movement, idempotência e integridade de reversão](0020-financial-movement-persistence-idempotency-and-reversal-integrity.md)
- [ADR-0021 — Transferências internas atômicas no ledger canônico](0021-atomic-internal-transfers.md)
- [ADR-0022 — Classificação e rateio append-only de Movements](0022-movement-classification-and-allocation.md)
- [ADR-0023 — Audit trail financeiro transacional e sem snapshot sensível](0023-financial-transactional-audit-trail.md)
- [ADR-0024 — Regras determinísticas de categorização com proveniência append-only](0024-deterministic-categorization-rules.md)
- [ADR-0025 — Caixa de pendências derivada, paginada por keyset e sem estado persistido](0025-derived-pending-classification-inbox.md)
- [ADR-0026 — Orçamentos mensais por categoria como planejamento derivado do ledger](0026-monthly-category-budgets.md)
- [ADR-0027 — Recorrências mensais manuais: regra é modelo, ocorrência é instância, Movement é o único fato](0027-manual-monthly-recurrences.md)
- [ADR-0028 — Sugestões assistidas de recorrência: derivadas, determinísticas e sempre confirmadas](0028-assisted-recurrence-suggestions.md)
- [ADR-0029 — Metas financeiras com destinação virtual de saldo existente](0029-financial-goals-with-virtual-allocation.md)

## Decisões propostas

- [ADR-0030 — Projetos como associação analítica auditável a despesas](0030-financial-projects-and-expense-links.md)

- [ADR-0009 — Stitch como referência visual e arquitetura de informação canônica](0009-stitch-reference-and-canonical-information-architecture.md)
- [ADR-0010 — Livro financeiro canônico e invariantes entre módulos](0010-canonical-ledger-and-cross-module-financial-invariants.md)
- [ADR-0011 — Fixtures demonstrativas determinísticas e relógio de referência](0011-deterministic-demo-fixtures-and-reference-clock.md)

## Decisões superseded

- [ADR-0001 — Aplicação local com interface PWA](0001-local-first-pwa.md), superseded pelo ADR-0008 na escolha do cliente.
- [ADR-0007 — Shell Web, design system mínimo e cache seguro da PWA](0007-web-shell-design-system-and-safe-pwa-cache.md), superseded pelo ADR-0008 na implementação do shell; seus contratos de segurança e acessibilidade foram preservados.

## Estados

- `Proposed`: em discussão.
- `Accepted`: decisão vigente.
- `Superseded`: substituída por outro ADR.
- `Rejected`: avaliada e não adotada.

## Numeração

Use números sequenciais com quatro dígitos:

```text
0001-local-first-pwa.md
0002-provider-adapters.md
```

## Template

```markdown
# ADR-NNNN — Título

- Status: Proposed
- Data: YYYY-MM-DD
- Decisores: mantenedores

## Contexto

## Decisão

## Alternativas consideradas

## Consequências positivas

## Consequências negativas e riscos

## Validação

## Referências
```

Uma PR que altera uma decisão aceita deve criar um novo ADR e marcar o anterior como `Superseded`.
