# meufinanceiro-persistence

Pacote interno compartilhado pela API, Worker, bootstrap e migração.

Responsabilidades:

- engine SQLAlchemy e transações explícitas;
- Alembic e revisão de schema;
- health de banco e migração;
- fila PostgreSQL com idempotência, lease, retry e recuperação;
- CLI operacional mínima para o smoke test.

O contrato estrutural está no [ADR-0006](../../docs/adr/0006-postgresql-persistence-and-task-queue.md). A operação está documentada em [PERSISTENCE_AND_TASK_QUEUE.md](../../docs/runbooks/PERSISTENCE_AND_TASK_QUEUE.md).
