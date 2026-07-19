"""Shared PostgreSQL persistence primitives for MeuFinanceiro."""

from meufinanceiro_persistence.database import Database
from meufinanceiro_persistence.health import (
    PersistenceHealth,
    inspect_persistence_health,
)
from meufinanceiro_persistence.queue import (
    LostLeaseError,
    TaskQueue,
    TaskRecord,
    TaskStatus,
)

__all__ = [
    "Database",
    "LostLeaseError",
    "PersistenceHealth",
    "TaskQueue",
    "TaskRecord",
    "TaskStatus",
    "inspect_persistence_health",
]
