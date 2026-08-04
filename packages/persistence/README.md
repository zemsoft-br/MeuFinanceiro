# meufinanceiro-persistence

Pacote interno compartilhado pela API, Worker, bootstrap e migração.

Responsabilidades:

- engine SQLAlchemy e transações explícitas;
- Alembic e revisão de schema;
- health de banco e migração;
- fila PostgreSQL com idempotência, lease, retry e recuperação;
- fixture determinística da fundação demo;
- configuração bancária cifrada por instalação;
- uso efêmero de credenciais somente para configuração habilitada;
- conexões e capacidades bancárias isoladas por RLS de residência;
- CLI operacional mínima para o smoke test.

A persistência bancária usa o schema `integrations`, envelopes autenticados do pacote
`meufinanceiro-security`, compare-and-swap por revisão e contexto transacional
fail-closed. A API instancia o store para o serviço administrativo interno, mas o
provider Pluggy continua não registrado e nenhuma chamada externa é executada.

O acesso ao plaintext usa `use_enabled_credentials`: envelopes são lidos em transação,
decriptados com AAD contextual e entregues somente a um callback interno depois do
encerramento da transação. Records administrativos comuns continuam sem envelopes ou
credenciais.

O contrato estrutural geral está no
[ADR-0006](../../docs/adr/0006-postgresql-persistence-and-task-queue.md). A operação da
fila está documentada em
[PERSISTENCE_AND_TASK_QUEUE.md](../../docs/runbooks/PERSISTENCE_AND_TASK_QUEUE.md). O
recorte bancário está descrito em
[BANKING_PERSISTENCE_IMPLEMENTATION.md](../../docs/architecture/BANKING_PERSISTENCE_IMPLEMENTATION.md)
e em
[BANKING_ENABLED_CREDENTIALS.md](../../docs/architecture/BANKING_ENABLED_CREDENTIALS.md).
