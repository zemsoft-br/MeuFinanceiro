# ADR-0023 — Audit trail financeiro transacional e sem snapshot sensível

- Status: Accepted
- Data: 2026-08-13
- Decisores: mantenedores

## Contexto

O ledger canônico já preserva a história econômica dos Movements, mas isso não responde sozinho a todas as perguntas operacionais sobre quem executou uma mutação financeira e quando ela foi commitada.

Contas, categorias, saldo de abertura, Movements e futuras transferências/rateios precisam compartilhar um mecanismo de auditoria consistente. Ao mesmo tempo, copiar amount, descrição, nome de conta, payload bancário ou snapshots inteiros para uma tabela genérica criaria uma segunda superfície de dados sensíveis e aumentaria o risco de divergência e vazamento.

O projeto também é local/self-hosted. Um administrador com controle suficiente do sistema operacional/PostgreSQL sempre pode modificar os dados. Portanto, o objetivo desta decisão não é prometer imutabilidade criptográfica contra o dono da infraestrutura, e sim garantir atomicidade, append-only no runtime, RLS e rastreabilidade dentro do modelo de ameaça da aplicação.

## Decisão

### Audit trail não é ledger nem snapshot

A auditoria registra somente evidência operacional mínima:

```text
quem
fez o quê
sobre qual recurso
em qual residência
quando
qual recurso relacionado participou, quando necessário
```

Ela não participa de saldo, resultado econômico, categorização ou autorização do recurso original.

Não são copiados para o audit trail:

```text
amount
currency
description
reason
nome de conta/categoria
request body
request digest
payload de provider
IDs externos
credenciais/tokens
raw JSON
before/after snapshot
```

A fonte de verdade continua sendo o recurso financeiro autoritativo.

### Tipos fechados

O domínio define `FinancialAuditEventType` e `FinancialAuditSubjectType` como enums fechados.

Eventos iniciais:

```text
ACCOUNT_CREATED
CATEGORY_CREATED
OPENING_BALANCE_CREATED
MOVEMENT_CREATED
MOVEMENT_REVERSED
TRANSFER_CREATED
TRANSFER_REVERSED
ALLOCATION_SET_CREATED
ALLOCATION_SET_REVISED
```

Subjects:

```text
ACCOUNT
CATEGORY
OPENING_BALANCE
MOVEMENT
TRANSFER
ALLOCATION_SET
```

O `event_type` determina o único `subject_type` válido. O chamador não escolhe a combinação livremente.

### Related subject também é tipado

Eventos simples de criação não possuem related subject.

Eventos que representam relação com uma operação anterior exigem related subject:

```text
MOVEMENT_REVERSED      -> related MOVEMENT original
TRANSFER_REVERSED      -> related TRANSFER original
ALLOCATION_SET_REVISED -> related ALLOCATION_SET predecessor
```

Subject e related subject precisam ser IDs distintos.

### Versão do contrato

Todo evento persiste `event_schema_version`.

A primeira versão é:

```text
1
```

A versão permite evoluir significado/shape sem reinterpretar silenciosamente eventos antigos. Não é versão de API HTTP.

### Identidade e timestamp server-side

`audit_event.id` é UUID v4 local e opaco conforme ADR-0017.

`occurred_at` é produzido no PostgreSQL com `transaction_timestamp()`; clientes não fornecem horário autoritativo do evento.

### Atomicidade obrigatória

Audit event e mutação financeira usam a mesma transação PostgreSQL.

Invariante:

```text
mutação commitou -> audit commitou
mutação rollback -> audit rollback
falha do audit -> mutação falha
```

Não existe best-effort, fila assíncrona ou segundo commit para a auditoria obrigatória da Fase 1.

A persistence deve expor apenas uma primitive interna connection-scoped, equivalente a:

```text
_append_financial_audit_event(connection, ...)
```

A primitive não abre nova transação.

### Replay não é nova mutação

Eventos acompanham criação física nova, não invocação de método.

Em uma operação idempotente de Movement:

```text
INSERT vencedor -> Movement + 1 audit event
retry replay     -> mesmo Movement + 0 novos audit events
```

O mesmo princípio vale para transferências/rateios quando forem integrados.

### Audiência actor-only no primeiro recorte

Uma tabela genérica de auditoria pode revelar a existência de recursos privados. Para evitar esse vazamento, a primeira política de leitura é restrita ao ator que executou a mutação.

Requisitos:

```text
residence corrente
membership ativa
actor_operator_id = current operator
```

Não há visão administrativa household-wide nesta etapa.

Uma futura expansão precisa de contrato explícito de permissão/redaction; não será inferida automaticamente de role de residência.

### Append-only e privilégios

`finance.audit_events` será append-only.

Runtime:

```text
SELECT conforme RLS
UPDATE proibido
DELETE proibido
```

A escrita deve ser protegida para impedir fabricação arbitrária de eventos. A implementação pode usar INSERT restrito por RLS/constraints ou uma função estreita `SECURITY DEFINER`, mas, se usar definer:

- `search_path` fixo em `pg_catalog, pg_temp`;
- schemas sempre qualificados;
- `PUBLIC EXECUTE` revogado;
- somente o role runtime configurado recebe EXECUTE;
- nenhuma função retorna payload financeiro.

### Integração progressiva

Stores existentes que criam recurso financeiro passam a anexar evento na própria transação:

```text
FinancialAccountStore.create_account
FinancialCategoryStore.create_category
opening balance create
FinancialMovementStore.create_movement
FinancialMovementStore.reverse_movement
```

Quando os recortes futuros forem reconciliados:

```text
transfer create/reverse
allocation set create/revise
```

Não se cria mutação fictícia como archive/disable apenas para completar lista de auditoria. Esses eventos só entram quando a operação real existir.

### Sem falsas garantias de tamper-proof

Append-only do runtime não equivale a imutabilidade contra administrador PostgreSQL/root.

Hash chain/assinatura digital não é adicionada nesta fase porque um administrador local capaz de alterar banco/aplicação também pode recomputar material sem uma âncora externa confiável.

Se no futuro houver requisito regulatório de não-repúdio, ele precisa de threat model e âncora externa próprios.

## Alternativas consideradas

### Auditar por logs de aplicação

Rejeitada como única fonte. Logs podem ser rotacionados, falhar separadamente e não oferecem atomicidade com o commit financeiro.

### Copiar snapshot before/after

Rejeitada. Duplica dados sensíveis, aumenta divergência e transforma auditoria em segunda representação de estado.

### JSON payload genérico

Rejeitado. Facilita vazamento acidental, perde matriz tipada e torna contratos difíceis de governar.

### Auditoria assíncrona

Rejeitada para eventos obrigatórios. Pode existir futuramente para exportação/SIEM, mas não substitui o evento transacional local.

### Tornar todo audit household-visible

Rejeitada inicialmente por risco de revelar recursos PERSONAL/SHARED por meio da tabela genérica.

### Hash chain local

Adiada/rejeitada nesta fase por não fornecer proteção real contra o administrador da própria infraestrutura sem âncora externa.

## Consequências positivas

- cada mutação bem-sucedida possui evidência operacional consistente;
- rollback não deixa evento órfão;
- retries idempotentes não poluem histórico;
- audit trail não replica amount/descrições/payload bancário;
- matriz event/subject é explícita;
- privacidade inicial é fail-closed actor-only;
- runtime não edita nem apaga eventos.

## Consequências negativas e riscos

- stores existentes precisarão de refatoração connection-scoped para anexar auditoria;
- auditoria actor-only não atende ainda investigação household-wide;
- consultas precisam resolver detalhes do recurso na fonte autoritativa quando autorizado;
- administrador da infraestrutura continua capaz de adulterar banco fora do modelo do runtime.

## Validação

A implementação deve provar:

- um evento por mutação física nova;
- zero eventos extras em replay;
- atomicidade mutação/audit;
- matriz fechada event/subject;
- related subject obrigatório/proibido conforme evento;
- timestamp server-side;
- actor/residence não spoofáveis;
- RLS actor-only;
- runtime sem UPDATE/DELETE;
- ausência de payload financeiro sensível;
- erros sanitizados;
- downgrade/reupgrade simétricos quando a migration for criada.

## Referências

- #124
- #171
- ADR-0016
- ADR-0017
- ADR-0018
- ADR-0019
- ADR-0020
- `docs/architecture/FINANCIAL_INVARIANTS.md`
