# ADR-0006 — Persistência e fila de tarefas no PostgreSQL

- Status: Accepted
- Data: 2026-07-19
- Decisores: mantenedores

## Contexto

A API e o Worker precisam compartilhar transações, migrações e trabalho assíncrono antes da implementação do domínio financeiro. A fundação deve continuar simples para instalações autohospedadas, sobreviver a reinícios e impedir que dois Workers executem a mesma reserva simultaneamente.

Adicionar Redis, RabbitMQ ou outro broker nesta fase aumentaria a superfície operacional, o consumo de recursos e o procedimento de backup. Uma fila ingênua baseada apenas em `SELECT` e `UPDATE` separados criaria corrida entre consumidores.

## Decisão

1. PostgreSQL permanece como persistência principal e também hospeda a fila fundacional.
2. `packages/persistence` concentra engine, transações explícitas, health de banco/schema, Alembic e contrato da fila.
3. Sessões e conexões são curtas; cada unidade de trabalho possui limite transacional explícito.
4. Migrações executam por serviço one-shot antes da API e do Worker.
5. Objetos da fila ficam no schema `infra`, separados dos futuros schemas funcionais.
6. Bootstrap e migração usam a role administrativa local. API e Worker usam uma role de runtime sem `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `REPLICATION` ou `BYPASSRLS`.
7. A fila possui os estados `pending`, `running`, `succeeded`, `failed` e `cancelled`.
8. A reserva usa `FOR UPDATE SKIP LOCKED`, incrementa a tentativa e cria um lease com `lease_token`, proprietário e expiração. Comparações e prazos do lease usam o relógio transacional do PostgreSQL, evitando divergência entre relógios dos processos.
9. Finalização, falha e renovação exigem o mesmo lease ainda válido. Enquanto um handler executa, o Worker renova o lease periodicamente; um Worker com lease antigo não pode concluir tarefa recuperada por outro consumidor.
10. Locks expirados podem ser reservados novamente enquanto houver tentativas. Locks expirados sem tentativas restantes tornam-se falhas terminais auditáveis.
11. `idempotency_key` possui unicidade global. Repetir o enqueue retorna a tarefa existente.
12. Retry usa `available_at` e backoff exponencial limitado. Erros persistidos são sanitizados e truncados.
13. Handlers formam allowlist. O handler demonstrativo registra seu efeito com chave única por tarefa, permitindo retry sem duplicar o efeito.
14. Health separa processo, conectividade do banco e revisão do schema/Alembic.

## Alternativas consideradas

### Redis ou broker externo

Rejeitado na fundação. Entregaria recursos adicionais, mas exigiria outro serviço, persistência, backup e operação. Pode ser reavaliado se métricas reais demonstrarem limite do PostgreSQL.

### Advisory locks

Rejeitado como contrato principal. Exigiria protocolo próprio para descoberta, expiração e recuperação, enquanto locks de linha tornam a reserva visível e transacional.

### Remover a tarefa ao reservar

Rejeitado. Perderia histórico, auditoria de falhas e recuperação após interrupção.

### Garantia genérica de exactly-once

Rejeitada como promessa global. Falhas entre o efeito externo e a confirmação da tarefa impedem exactly-once universal. A fundação fornece enqueue idempotente, lease seguro e um padrão de efeito idempotente; cada handler futuro deve definir sua própria chave de idempotência/transação.

## Consequências positivas

- uma única tecnologia persistente na instalação inicial;
- tarefas sobrevivem a restart;
- consumidores concorrentes não recebem a mesma reserva;
- falhas e tentativas permanecem auditáveis;
- API e Worker não possuem privilégios administrativos;
- readiness detecta banco indisponível e schema desatualizado separadamente;
- migrações podem ser validadas com upgrade e downgrade em PostgreSQL real.

## Consequências negativas e riscos

- a fila compartilha capacidade com o banco principal;
- consultas e índices da fila precisarão de observação conforme o volume crescer;
- leases exigem heartbeat ativo; indisponibilidade prolongada do banco pode tornar a propriedade incerta e requer efeitos idempotentes;
- idempotência de enqueue não elimina a obrigação de handlers idempotentes;
- alterações futuras de schema precisam preservar grants da role de runtime.

## Validação

- upgrade e downgrade da migração inicial em PostgreSQL descartável;
- teste com dois consumidores concorrentes;
- teste de idempotency key;
- recuperação de lease expirado e falha terminal;
- rejeição de finalização com lease antigo;
- efeito demonstrativo único após execução repetida;
- Compose com bootstrap, migração, API e Worker;
- verificação automatizada dos atributos da role de runtime.

## Referências

- PostgreSQL 18 — `SELECT`, locking e `SKIP LOCKED`: https://www.postgresql.org/docs/18/sql-select.html
- PostgreSQL 18 — `UPDATE` com CTE e `SKIP LOCKED`: https://www.postgresql.org/docs/18/sql-update.html
- SQLAlchemy 2.0 — transações e context managers: https://docs.sqlalchemy.org/en/20/orm/session_transaction.html
- Alembic 1.18.5 — comandos programáticos: https://alembic.sqlalchemy.org/en/latest/api/commands.html
