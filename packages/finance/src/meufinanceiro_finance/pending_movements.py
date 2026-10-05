"""Provider-neutral contracts of the derived pending-classification inbox.

A pending Movement is a *derived* fact, never persisted state: at the current
canonical state it is a STANDARD INCOME/EXPENSE Movement, visible to the operator,
with no allocation set. Nothing here is a second authority: the ledger stays in
``finance.movements`` and classification stays in ``movement_allocation_sets``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from meufinanceiro_finance.access import FinancialVisibilityScope
from meufinanceiro_finance.accounts import FinancialAccountStatus
from meufinanceiro_finance.ids import validate_financial_resource_id
from meufinanceiro_finance.movement_records import FinancialMovementRecord

PENDING_PAGE_LIMIT_DEFAULT = 50
PENDING_PAGE_LIMIT_MAX = 100


@dataclass(frozen=True, slots=True, repr=False)
class FinancialPendingMovementKey:
    """Keyset position of a pending Movement: ``effective_date`` then ``id``.

    The order is ``effective_date DESC, id DESC``. The key is an exact ledger
    coordinate, so it stays valid when Movements are appended or classified
    concurrently (unlike an offset).
    """

    effective_date: date
    movement_id: UUID

    def __post_init__(self) -> None:
        if type(self.effective_date) is not date:
            raise TypeError("effective_date must be date")
        validate_financial_resource_id(self.movement_id)

    def __repr__(self) -> str:
        return "FinancialPendingMovementKey(<position-redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialPendingMovementCandidate:
    """One unclassified, visible Movement with the account facts that rules need.

    Account facts come from the same row read, so evaluating rules and deciding
    ``can_classify`` never costs another read per Movement or per account.
    """

    movement: FinancialMovementRecord
    account_visibility_scope: FinancialVisibilityScope
    account_owner_operator_id: UUID
    account_status: FinancialAccountStatus

    def __post_init__(self) -> None:
        if not isinstance(self.movement, FinancialMovementRecord):
            raise TypeError("movement must be FinancialMovementRecord")
        if not isinstance(self.account_visibility_scope, FinancialVisibilityScope):
            raise TypeError("account_visibility_scope must be FinancialVisibilityScope")
        if not isinstance(self.account_owner_operator_id, UUID):
            raise TypeError("account_owner_operator_id must be UUID")
        if not isinstance(self.account_status, FinancialAccountStatus):
            raise TypeError("account_status must be FinancialAccountStatus")

    @property
    def key(self) -> FinancialPendingMovementKey:
        return FinancialPendingMovementKey(
            effective_date=self.movement.effective_date,
            movement_id=self.movement.id,
        )

    def can_classify(self, operator_id: UUID) -> bool:
        """Whether the operator could classify it: owner of an ACTIVE account.

        Mirrors the write authority of manual classification and rule apply
        (``_owned_active_account``). A visible item may still be read-only.
        """
        return (
            self.account_owner_operator_id == operator_id
            and self.account_status is FinancialAccountStatus.ACTIVE
        )

    def __repr__(self) -> str:
        return "FinancialPendingMovementCandidate(<movement-redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class FinancialPendingMovementCandidatePage:
    """A bounded keyset page of candidates, in ``effective_date DESC, id DESC``."""

    candidates: tuple[FinancialPendingMovementCandidate, ...]
    has_more: bool

    def __post_init__(self) -> None:
        if len(self.candidates) > PENDING_PAGE_LIMIT_MAX:
            raise ValueError("pending page exceeds the maximum page size")
        if self.has_more and not self.candidates:
            raise ValueError("an empty page cannot have more candidates")

    def __repr__(self) -> str:
        return (
            f"FinancialPendingMovementCandidatePage(size={len(self.candidates)}, "
            f"has_more={self.has_more})"
        )


__all__ = [
    "PENDING_PAGE_LIMIT_DEFAULT",
    "PENDING_PAGE_LIMIT_MAX",
    "FinancialPendingMovementCandidate",
    "FinancialPendingMovementCandidatePage",
    "FinancialPendingMovementKey",
]
