from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from meufinanceiro_finance import (
    FinancialAccessDeniedError,
    FinancialActorContext,
    FinancialResourceAudience,
    FinancialVisibilityScope,
    can_access_financial_resource,
    require_financial_resource_access,
)


def _actor(
    *,
    residence_id: UUID,
    operator_id: UUID,
    active: bool = True,
) -> FinancialActorContext:
    return FinancialActorContext(
        residence_id=residence_id,
        operator_id=operator_id,
        membership_active=active,
    )


def test_personal_scope_allows_only_active_owner_in_same_residence() -> None:
    residence_id = uuid4()
    owner_id = uuid4()
    other_id = uuid4()
    audience = FinancialResourceAudience(
        residence_id=residence_id,
        owner_operator_id=owner_id,
        visibility_scope=FinancialVisibilityScope.PERSONAL,
    )

    assert can_access_financial_resource(
        _actor(residence_id=residence_id, operator_id=owner_id),
        audience,
    )
    assert not can_access_financial_resource(
        _actor(residence_id=residence_id, operator_id=other_id),
        audience,
    )
    assert not can_access_financial_resource(
        _actor(residence_id=residence_id, operator_id=owner_id, active=False),
        audience,
    )


def test_shared_scope_allows_owner_and_explicit_grants_only() -> None:
    residence_id = uuid4()
    owner_id = uuid4()
    granted_id = uuid4()
    ungranted_id = uuid4()
    audience = FinancialResourceAudience(
        residence_id=residence_id,
        owner_operator_id=owner_id,
        visibility_scope=FinancialVisibilityScope.SHARED,
        shared_operator_ids=frozenset({granted_id}),
    )

    assert can_access_financial_resource(
        _actor(residence_id=residence_id, operator_id=owner_id),
        audience,
    )
    assert can_access_financial_resource(
        _actor(residence_id=residence_id, operator_id=granted_id),
        audience,
    )
    assert not can_access_financial_resource(
        _actor(residence_id=residence_id, operator_id=ungranted_id),
        audience,
    )
    assert not can_access_financial_resource(
        _actor(
            residence_id=residence_id,
            operator_id=granted_id,
            active=False,
        ),
        audience,
    )


def test_household_scope_allows_any_active_same_residence_member() -> None:
    residence_id = uuid4()
    audience = FinancialResourceAudience(
        residence_id=residence_id,
        owner_operator_id=uuid4(),
        visibility_scope=FinancialVisibilityScope.HOUSEHOLD,
    )

    assert can_access_financial_resource(
        _actor(residence_id=residence_id, operator_id=uuid4()),
        audience,
    )
    assert not can_access_financial_resource(
        _actor(residence_id=residence_id, operator_id=uuid4(), active=False),
        audience,
    )


def test_cross_residence_always_fails_closed() -> None:
    audience = FinancialResourceAudience(
        residence_id=uuid4(),
        owner_operator_id=uuid4(),
        visibility_scope=FinancialVisibilityScope.HOUSEHOLD,
    )

    assert not can_access_financial_resource(
        _actor(residence_id=uuid4(), operator_id=uuid4()),
        audience,
    )


def test_explicit_grants_are_valid_only_for_shared_scope() -> None:
    residence_id = uuid4()
    owner_id = uuid4()
    granted_id = uuid4()

    for visibility_scope in (
        FinancialVisibilityScope.PERSONAL,
        FinancialVisibilityScope.HOUSEHOLD,
    ):
        with pytest.raises(ValueError, match="only for SHARED"):
            FinancialResourceAudience(
                residence_id=residence_id,
                owner_operator_id=owner_id,
                visibility_scope=visibility_scope,
                shared_operator_ids=frozenset({granted_id}),
            )


def test_owner_redundant_shared_grant_is_rejected() -> None:
    residence_id = uuid4()
    owner_id = uuid4()

    with pytest.raises(ValueError, match="redundant"):
        FinancialResourceAudience(
            residence_id=residence_id,
            owner_operator_id=owner_id,
            visibility_scope=FinancialVisibilityScope.SHARED,
            shared_operator_ids=frozenset({owner_id}),
        )


def test_access_contract_rejects_untrusted_shapes() -> None:
    with pytest.raises(TypeError):
        FinancialActorContext(  # type: ignore[arg-type]
            residence_id="not-a-uuid",
            operator_id=uuid4(),
            membership_active=True,
        )
    with pytest.raises(TypeError):
        FinancialActorContext(  # type: ignore[arg-type]
            residence_id=uuid4(),
            operator_id=uuid4(),
            membership_active=1,
        )
    with pytest.raises(TypeError):
        FinancialResourceAudience(  # type: ignore[arg-type]
            residence_id=uuid4(),
            owner_operator_id=uuid4(),
            visibility_scope="PERSONAL",
        )
    with pytest.raises(TypeError):
        FinancialResourceAudience(  # type: ignore[arg-type]
            residence_id=uuid4(),
            owner_operator_id=uuid4(),
            visibility_scope=FinancialVisibilityScope.SHARED,
            shared_operator_ids={uuid4()},
        )


def test_require_access_raises_sanitized_error() -> None:
    residence_id = uuid4()
    owner_id = uuid4()
    outsider_id = uuid4()
    audience = FinancialResourceAudience(
        residence_id=residence_id,
        owner_operator_id=owner_id,
        visibility_scope=FinancialVisibilityScope.PERSONAL,
    )

    with pytest.raises(FinancialAccessDeniedError) as captured:
        require_financial_resource_access(
            _actor(residence_id=residence_id, operator_id=outsider_id),
            audience,
        )

    assert str(captured.value) == "financial resource access denied"
    assert str(residence_id) not in str(captured.value)
    assert str(owner_id) not in str(captured.value)
    assert str(outsider_id) not in str(captured.value)


def test_repr_redacts_residence_and_operator_ids() -> None:
    residence_id = uuid4()
    owner_id = uuid4()
    granted_id = uuid4()
    actor = _actor(residence_id=residence_id, operator_id=owner_id)
    audience = FinancialResourceAudience(
        residence_id=residence_id,
        owner_operator_id=owner_id,
        visibility_scope=FinancialVisibilityScope.SHARED,
        shared_operator_ids=frozenset({granted_id}),
    )

    actor_repr = repr(actor)
    audience_repr = repr(audience)
    for sensitive in (residence_id, owner_id, granted_id):
        assert str(sensitive) not in actor_repr
        assert str(sensitive) not in audience_repr
    assert "membership_active=True" in actor_repr
    assert "SHARED" in audience_repr
    assert "shared_count=1" in audience_repr
