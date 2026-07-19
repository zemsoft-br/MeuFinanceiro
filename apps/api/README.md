# API

FastAPI responsável pelo contrato HTTP `/api/v1`.

A API utiliza `meufinanceiro-persistence` com a role PostgreSQL de runtime e só inicia depois que o serviço `migrate` conclui. Liveness verifica o processo; readiness verifica separadamente banco e revisão Alembic.

A interface visual permanece fora deste pacote.
