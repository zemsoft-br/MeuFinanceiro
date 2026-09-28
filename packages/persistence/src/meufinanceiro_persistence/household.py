"""Public household persistence contracts."""

from meufinanceiro_persistence import household_schema as _household_schema
from meufinanceiro_persistence.household_models import (
    HouseholdBootstrapConflictError,
    HouseholdPersistenceError,
    MembershipRole,
    MembershipStatus,
    PrimaryResidenceRecord,
    ResidenceStatus,
    normalize_residence_name,
)

# Importing the schema module registers its tables on the shared metadata.
del _household_schema

__all__ = [
    "HouseholdBootstrapConflictError",
    "HouseholdPersistenceError",
    "MembershipRole",
    "MembershipStatus",
    "PrimaryResidenceRecord",
    "ResidenceStatus",
    "normalize_residence_name",
]
