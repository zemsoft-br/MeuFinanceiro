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
- conexões bancárias vinculadas por FK à residência canônica da mesma instalação;
- CLI operacional mínima para o smoke test.

A persistência bancária usa o schema `integrations`, envelopes autenticados do pacote
`meufinanceiro-security`, compare-and-swap por revisão e contexto transacional
fail-closed. Toda linha de `integrations.connections` referencia
`household.residences(id, installation_id)` com `ON DELETE RESTRICT`; upgrades com
referências órfãs são recusados sem sintetizar ou remapear residências. A API instancia
o store para o serviço administrativo interno, mas nenhuma conexão HTTP bancária aceita
`residence_id` arbitrário do cliente.

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
