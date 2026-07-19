# Architecture Decision Records

ADRs registram decisões estruturais, contexto, alternativas e consequências.

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
