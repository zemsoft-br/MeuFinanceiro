# ADR-0010 — Livro financeiro canônico e invariantes entre módulos

- Status: Proposed
- Data: 2026-07-19
- Decisores: mantenedores

## Contexto

O produto inclui contas, cartões, orçamentos, recorrências, metas, projetos, importações, Pluggy, empréstimos e patrimônio. Sem uma decisão explícita, cada módulo pode registrar efeitos semelhantes e provocar dupla contabilização.

`docs/ARCHITECTURE.md` já define o modelo local como fonte de verdade e apresenta conceitos de livro. A cobertura do Stitch evidenciou a necessidade de consolidar as regras que atravessam todos os módulos antes da primeira funcionalidade financeira.

## Decisão

1. Haverá um único livro financeiro canônico para eventos realizados e liquidações.
2. Módulos podem manter projeções, observações, agregados e vínculos, mas não outro ledger.
3. Transferências internas não são receitas nem despesas.
4. Compra de cartão é despesa; pagamento da fatura é liquidação.
5. Planejado, comprometido, realizado e projetado são conceitos distintos.
6. Regra recorrente e ocorrência projetada não são movimentações.
7. Destinação virtual para meta não cria dinheiro ou ativo.
8. Registro importado ou externo não é movimento sem confirmação ou regra autorizada.
9. Recebimento de empréstimo aumenta caixa e passivo, não receita.
10. Principal pago reduz caixa e passivo; encargos são custos financeiros.
11. Aporte e resgate pelo principal são transferências patrimoniais.
12. Valorização altera avaliação, não caixa.
13. Correções relevantes são reversíveis e auditadas.
14. Autorização e escopo acompanham o registro original em relatórios, alertas, exportações e diagnósticos.

O contrato detalhado está em `docs/architecture/FINANCIAL_INVARIANTS.md`.

## Alternativas consideradas

### Um ledger por módulo

Rejeitada por duplicação, conciliação impossível e relatórios inconsistentes.

### Uma única tabela genérica para todo conceito

Rejeitada. Livro canônico não significa eliminar semântica de compras, faturas, parcelas, ocorrências, observações ou posições.

### Regras apenas no cliente

Rejeitada. Interfaces Flutter, Web ou mobile não protegem concorrência, integração, autorização ou consistência do backend.

### Aceitar totais informados pelas telas

Rejeitada. Totais derivados devem ser recalculados por fonte central.

## Consequências positivas

- relatórios consistentes;
- importação e Pluggy convergem para o mesmo modelo;
- testes financeiros reutilizáveis;
- menor risco de dupla contabilização;
- correções rastreáveis;
- projeções isoladas de dados realizados.

## Consequências negativas e riscos

- exige modelagem cuidadosa de agregados;
- algumas operações precisam de transações multi-entidade;
- relatórios podem exigir projeções especializadas;
- decisões adicionais sobre dinheiro, IDs e imutabilidade continuam pendentes;
- migrações futuras precisam preservar vínculos.

## Validação

Antes da primeira funcionalidade financeira:

- ADR de representação monetária;
- modelo de movimento e saldo de abertura;
- testes de transferências;
- testes de compra e liquidação de fatura;
- testes de importação idempotente;
- testes de principal e juros;
- testes de aporte e valorização;
- testes de autorização.

## Referências

- ADR-0002 — Fonte local de verdade e adaptadores
- ADR-0008 — Flutter como cliente canônico multiplataforma
- `docs/ARCHITECTURE.md`
- `docs/PRODUCT_SPECIFICATION.md`
- `docs/architecture/FINANCIAL_INVARIANTS.md`
- Issue #22
