"""Public identity persistence contracts."""

from meufinanceiro_persistence import identity_schema as _identity_schema
from meufinanceiro_persistence.identity_models import (
    IdentityBootstrapConflictError,
    IdentityPersistenceError,
    InstallationOperatorRecord,
    OperatorAuthenticationMaterial,
    OperatorRole,
    OperatorSessionPrincipal,
    OperatorStatus,
    normalize_operator_login,
    validate_token_hash,
)
from meufinanceiro_persistence.identity_store import OperatorIdentityStore

# Importing the schema module registers its tables on the shared metadata and schema
# module before the store resolves those attributes.
del _identity_schema

__all__ = [
    "IdentityBootstrapConflictError",
    "IdentityPersistenceError",
    "InstallationOperatorRecord",
    "OperatorAuthenticationMaterial",
    "OperatorIdentityStore",
    "OperatorRole",
    "OperatorSessionPrincipal",
    "OperatorStatus",
    "normalize_operator_login",
    "validate_token_hash",
]
