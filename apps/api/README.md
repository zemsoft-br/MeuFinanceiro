# API

FastAPI responsável pelo contrato HTTP `/api/v1`.

A API utiliza `meufinanceiro-persistence` com a role PostgreSQL de runtime e só inicia depois que o serviço `migrate` conclui. Liveness verifica o processo; readiness verifica separadamente banco e revisão Alembic.

A interface visual permanece fora deste pacote.


## Núcleo financeiro autenticado

A superfície financeira deriva instalação, residência primária e operador da sessão autenticada. Escritas do ledger são semânticas; não existe `POST /finance/movements` genérico.

```text
POST /api/v1/finance/accounts/{account_id}/income
POST /api/v1/finance/accounts/{account_id}/expense
POST /api/v1/finance/movements/{movement_id}/reversal
POST /api/v1/finance/transfers
POST /api/v1/finance/transfers/{transfer_id}/reversal
GET  /api/v1/finance/accounts/{account_id}/balance
GET  /api/v1/finance/accounts/{account_id}/statement
```

Valores monetários são serializados como strings decimais. Operações mutáveis exigem `idempotencyKey` UUID v4. Saldo e extrato são projeções read-only do opening balance e dos Movements canônicos.
