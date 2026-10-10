"""Application boundary for project planning and audited expense links (#262).

Realized is always derived from the canonical Movement ledger at read time.
The store holds all access, idempotency and concurrency authority; nothing
in this service writes Movements or project realized amounts (ADR-0030).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from meufinanceiro_finance import (
    FinancialProjectDraft,
    FinancialProjectExpenseFact,
    FinancialProjectLinkRevisionDraft,
    FinancialProjectLinkRevisionRecord,
    FinancialProjectRecord,
    FinancialProjectReplacement,
    FinancialProjectSummary,
    summarize_project,
)


@runtime_checkable
class ProjectStoreBoundary(Protocol):
    def create_project(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialProjectDraft,
    ) -> FinancialProjectRecord: ...

    def get_project(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        project_id: UUID,
    ) -> FinancialProjectRecord: ...

    def list_projects(
        self, *, installation_id: UUID, residence_id: UUID, operator_id: UUID
    ) -> tuple[FinancialProjectRecord, ...]: ...

    def replace_project(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        project_id: UUID,
        replacement: FinancialProjectReplacement,
    ) -> FinancialProjectRecord: ...

    def revise_link(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialProjectLinkRevisionDraft,
    ) -> FinancialProjectLinkRevisionRecord: ...

    def get_link(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        movement_id: UUID,
    ) -> FinancialProjectLinkRevisionRecord | None: ...

    def read_link_history(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        movement_id: UUID,
    ) -> tuple[FinancialProjectLinkRevisionRecord, ...]: ...

    def read_project_facts(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        project_id: UUID,
    ) -> tuple[
        FinancialProjectRecord,
        tuple["FinancialProjectExpenseFact", ...],
    ]: ...


@dataclass(frozen=True, slots=True, repr=False)
class ProjectView:
    project: FinancialProjectRecord
    can_edit: bool

    def __repr__(self) -> str:
        return f"ProjectView(can_edit={self.can_edit})"


@dataclass(frozen=True, slots=True, repr=False)
class ProjectSummaryView:
    summary: FinancialProjectSummary
    expenses: tuple[FinancialProjectExpenseFact, ...]
    can_edit: bool

    def __repr__(self) -> str:
        return f"ProjectSummaryView(can_edit={self.can_edit})"


class FinancialProjectService:
    """Authenticated orchestration, no independent monetary authority."""

    def __init__(self, store: ProjectStoreBoundary) -> None:
        if not isinstance(store, ProjectStoreBoundary):
            raise TypeError("store must satisfy ProjectStoreBoundary")
        self._store = store

    def create_project(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialProjectDraft,
    ) -> ProjectView:
        project = self._store.create_project(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=idempotency_key,
            draft=draft,
        )
        return _view(project, operator_id)

    def list_projects(
        self, *, installation_id: UUID, residence_id: UUID, operator_id: UUID
    ) -> tuple[ProjectView, ...]:
        return tuple(
            _view(project, operator_id)
            for project in self._store.list_projects(
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=operator_id,
            )
        )

    def get_project(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        project_id: UUID,
    ) -> ProjectView:
        return _view(
            self._store.get_project(
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=operator_id,
                project_id=project_id,
            ),
            operator_id,
        )

    def replace_project(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        project_id: UUID,
        replacement: FinancialProjectReplacement,
    ) -> ProjectView:
        return _view(
            self._store.replace_project(
                installation_id=installation_id,
                residence_id=residence_id,
                operator_id=operator_id,
                project_id=project_id,
                replacement=replacement,
            ),
            operator_id,
        )

    def revise_link(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        idempotency_key: UUID,
        draft: FinancialProjectLinkRevisionDraft,
    ) -> FinancialProjectLinkRevisionRecord:
        return self._store.revise_link(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            idempotency_key=idempotency_key,
            draft=draft,
        )

    def get_link(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        movement_id: UUID,
    ) -> FinancialProjectLinkRevisionRecord | None:
        return self._store.get_link(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            movement_id=movement_id,
        )

    def read_link_history(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        movement_id: UUID,
    ) -> tuple[FinancialProjectLinkRevisionRecord, ...]:
        return self._store.read_link_history(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            movement_id=movement_id,
        )

    def summary(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        project_id: UUID,
    ) -> ProjectSummaryView:
        project, expenses = self._store.read_project_facts(
            installation_id=installation_id,
            residence_id=residence_id,
            operator_id=operator_id,
            project_id=project_id,
        )
        return ProjectSummaryView(
            summary=summarize_project(project, expenses),
            expenses=expenses,
            can_edit=project.owner_operator_id == operator_id,
        )


def _view(project: FinancialProjectRecord, operator_id: UUID) -> ProjectView:
    return ProjectView(
        project=project, can_edit=project.owner_operator_id == operator_id
    )


__all__ = [
    "FinancialProjectService",
    "ProjectStoreBoundary",
    "ProjectSummaryView",
    "ProjectView",
]
