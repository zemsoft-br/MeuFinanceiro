from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from meufinanceiro_finance import (
    FinancialCategoryDraft,
    FinancialCategoryRecord,
    FinancialCategoryStatus,
    FinancialVisibilityScope,
    new_financial_resource_id,
)

NOW = datetime(2026, 8, 11, 2, 30, tzinfo=UTC)


def test_category_draft_normalizes_name_and_accepts_personal_household() -> None:
    personal = FinancialCategoryDraft(
        name="  Alimentação  ",
        visibility_scope=FinancialVisibilityScope.PERSONAL,
    )
    household = FinancialCategoryDraft(
        name="Moradia",
        visibility_scope=FinancialVisibilityScope.HOUSEHOLD,
    )

    assert personal.name == "Alimentação"
    assert personal.parent_id is None
    assert household.visibility_scope is FinancialVisibilityScope.HOUSEHOLD


def test_shared_category_scope_is_explicitly_rejected() -> None:
    with pytest.raises(
        ValueError, match="SHARED category visibility is not supported yet"
    ):
        FinancialCategoryDraft(
            name="Compartilhada",
            visibility_scope=FinancialVisibilityScope.SHARED,
        )


def test_category_draft_validates_parent_as_financial_uuid4() -> None:
    parent_id = new_financial_resource_id()
    draft = FinancialCategoryDraft(
        name="Supermercado",
        visibility_scope=FinancialVisibilityScope.HOUSEHOLD,
        parent_id=parent_id,
    )
    assert draft.parent_id == parent_id

    with pytest.raises(TypeError):
        FinancialCategoryDraft(  # type: ignore[arg-type]
            name="Inválida",
            visibility_scope=FinancialVisibilityScope.PERSONAL,
            parent_id=str(parent_id),
        )


def test_category_record_rejects_self_parent() -> None:
    category_id = new_financial_resource_id()
    with pytest.raises(ValueError, match="own parent"):
        FinancialCategoryRecord(
            id=category_id,
            residence_id=uuid4(),
            owner_operator_id=uuid4(),
            visibility_scope=FinancialVisibilityScope.PERSONAL,
            parent_id=category_id,
            name="Inválida",
            status=FinancialCategoryStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
            disabled_at=None,
        )


def test_category_record_enforces_disabled_lifecycle() -> None:
    common = dict(
        id=new_financial_resource_id(),
        residence_id=uuid4(),
        owner_operator_id=uuid4(),
        visibility_scope=FinancialVisibilityScope.PERSONAL,
        parent_id=None,
        name="Categoria",
        created_at=NOW,
        updated_at=NOW,
    )
    with pytest.raises(ValueError, match="active category"):
        FinancialCategoryRecord(
            **common,
            status=FinancialCategoryStatus.ACTIVE,
            disabled_at=NOW,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        FinancialCategoryRecord(
            **common,
            status=FinancialCategoryStatus.DISABLED,
            disabled_at=None,
        )


def test_category_repr_redacts_name_and_ids() -> None:
    category_id = new_financial_resource_id()
    residence_id = uuid4()
    owner_id = uuid4()
    parent_id = new_financial_resource_id()
    record = FinancialCategoryRecord(
        id=category_id,
        residence_id=residence_id,
        owner_operator_id=owner_id,
        visibility_scope=FinancialVisibilityScope.HOUSEHOLD,
        parent_id=parent_id,
        name="Saúde íntima",
        status=FinancialCategoryStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
        disabled_at=None,
    )

    rendered = repr(record)
    for sensitive in (category_id, residence_id, owner_id, parent_id):
        assert str(sensitive) not in rendered
    assert "Saúde íntima" not in rendered
    assert "HOUSEHOLD" in rendered
    assert "has_parent=True" in rendered
