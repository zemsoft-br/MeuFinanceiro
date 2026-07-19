# Worker

Consumidor da fila PostgreSQL `infra.task_queue`.

O Worker reserva tarefas por lease, renova o lease enquanto o handler executa, usa uma allowlist de handlers, aplica retry com backoff limitado e recupera tarefas abandonadas. O handler `demo.echo` existe apenas para validar a fundação e registra efeito idempotente em `infra.demo_task_effects`.
