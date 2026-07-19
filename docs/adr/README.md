# Architecture Decision Records

ADRs registram decisões estruturais, contexto, alternativas e consequências.

## Decisões vigentes

- [ADR-0002 — Fonte local de verdade e adaptadores](0002-local-source-of-truth-and-adapters.md)
- [ADR-0003 — GitFlow e colaboração orientada a issues](0003-gitflow-and-issue-driven-collaboration.md)
- [ADR-0004 — Licença, contribuições e política de marca](0004-project-license-and-trademark.md)
- [ADR-0005 — Configuração segura, criptografia e gerenciamento de chaves](0005-security-configuration-and-key-management.md)
- [ADR-0006 — Persistência e fila de tarefas no PostgreSQL](0006-postgresql-persistence-and-task-queue.md)
- [ADR-0008 — Flutter como cliente canônico multiplataforma](0008-flutter-multiplatform-client.md)

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
