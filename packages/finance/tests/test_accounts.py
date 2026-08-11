from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from meufinanceiro_finance import (
    FinancialAccountDraft,
    FinancialAccountRecord,
    FinancialAccountStatus,
    FinancialAccountType,
    FinancialVisibilityScope,
    new_financial_resource_id,
    validate_currency_code,
)

NOW = datetime(2026, 8, 11, 1, 45, tzinfo=UTC)


def test_account_draft_normalizes_text_and_uses_canonical_currency() -> None:
    draft = FinancialAccountDraft(
        name="  Conta principal  ",
        currency="BRL",
        account_type=FinancialAccountType.CHECKING,
        visibility_scope=FinancialVisibilityScope.HOUSEHOLD,
    )

    assert draft.name == "Conta principal"
    assert draft.currency == "BRL"
    assert draft.custom_type_name is None


def test_custom_account_requires_custom_type_name() -> None:
    with pytest.raises(ValueError, match="required for CUSTOM"):
        FinancialAccountDraft(
            name="Conta",
            currency="BRL",
            account_type=FinancialAccountType.CUSTOM,
            visibility_scope=FinancialVisibilityScope.PERSONAL,
        )

    custom = FinancialAccountDraft(
        name="Conta",
        currency="BRL",
        account_type=FinancialAccountType.CUSTOM,
        visibility_scope=FinancialVisibilityScope.PERSONAL,
        custom_type_name="  Cofre doméstico  ",
    )
    assert custom.custom_type_name == "Cofre doméstico"


def test_non_custom_account_rejects_custom_type_name() -> None:
    with pytest.raises(ValueError, match="only for CUSTOM"):
        FinancialAccountDraft(
            name="Conta",
            currency="BRL",
            account_type=FinancialAccountType.CASH,
            visibility_scope=FinancialVisibilityScope.PERSONAL,
            custom_type_name="Dinheiro",
        )


def test_account_draft_rejects_invalid_name_currency_and_untrusted_enums() -> None:
    with pytest.raises(ValueError):
        FinancialAccountDraft(
            name="   ",
            currency="BRL",
            account_type=FinancialAccountType.CASH,
            visibility_scope=FinancialVisibilityScope.PERSONAL,
        )
    with pytest.raises(ValueError):
        FinancialAccountDraft(
            name="Conta",
            currency="brl",
            account_type=FinancialAccountType.CASH,
            visibility_scope=FinancialVisibilityScope.PERSONAL,
        )
    with pytest.raises(TypeError):
        FinancialAccountDraft(  # type: ignore[arg-type]
            name="Conta",
            currency="BRL",
            account_type="CASH",
            visibility_scope=FinancialVisibilityScope.PERSONAL,
        )
    with pytest.raises(TypeError):
        FinancialAccountDraft(  # type: ignore[arg-type]
            name="Conta",
            currency="BRL",
            account_type=FinancialAccountType.CASH,
            visibility_scope="PERSONAL",
        )


def test_currency_validator_is_shared_with_money_contract() -> None:
    assert validate_currency_code("USD") == "USD"
    with pytest.raises(ValueError):
        validate_currency_code("usd")


def test_active_account_record_has_no_archived_at_and_redacts_identity_name() -> None:
    account_id = new_financial_resource_id()
    residence_id = uuid4()
    owner_id = uuid4()
    record = FinancialAccountRecord(
        id=account_id,
        residence_id=residence_id,
        owner_operator_id=owner_id,
        visibility_scope=FinancialVisibilityScope.PERSONAL,
        account_type=FinancialAccountType.SAVINGS,
        custom_type_name=None,
        name="Reserva de emergência",
        currency="BRL",
        status=FinancialAccountStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
        archived_at=None,
    )

    rendered = repr(record)
    assert str(account_id) not in rendered
    assert str(residence_id) not in rendered
    assert str(owner_id) not in rendered
    assert "Reserva de emergência" not in rendered
    assert "SAVINGS" in rendered
    assert "ACTIVE" in rendered


def test_account_record_enforces_archive_state() -> None:
    common = dict(
        id=new_financial_resource_id(),
        residence_id=uuid4(),
        owner_operator_id=uuid4(),
        visibility_scope=FinancialVisibilityScope.PERSONAL,
        account_type=FinancialAccountType.CASH,
        custom_type_name=None,
        name="Carteira",
        currency="BRL",
        created_at=NOW,
        updated_at=NOW,
    )

    with pytest.raises(ValueError, match="active account"):
        FinancialAccountRecord(
            **common,
            status=FinancialAccountStatus.ACTIVE,
            archived_at=NOW,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        FinancialAccountRecord(
            **common,
            status=FinancialAccountStatus.ARCHIVED,
            archived_at=None,
        )
