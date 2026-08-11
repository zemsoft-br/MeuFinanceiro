from __future__ import annotations

from uuid import NAMESPACE_DNS, UUID, uuid5

import pytest

from meufinanceiro_finance import (
    new_financial_resource_id,
    validate_financial_resource_id,
)


def test_new_financial_resource_id_generates_non_nil_rfc4122_uuid4() -> None:
    resource_id = new_financial_resource_id()

    assert isinstance(resource_id, UUID)
    assert resource_id.int != 0
    assert resource_id.version == 4
    assert resource_id.variant == "specified in RFC 4122"


def test_generated_financial_resource_ids_are_distinct_in_synthetic_sample() -> None:
    generated = {new_financial_resource_id() for _ in range(64)}

    assert len(generated) == 64


def test_validator_returns_same_valid_uuid_without_coercion() -> None:
    resource_id = new_financial_resource_id()

    assert validate_financial_resource_id(resource_id) is resource_id


def test_validator_rejects_string_even_when_it_contains_valid_uuid4() -> None:
    resource_id = new_financial_resource_id()

    with pytest.raises(TypeError, match="must be UUID"):
        validate_financial_resource_id(str(resource_id))  # type: ignore[arg-type]


def test_validator_rejects_nil_uuid() -> None:
    with pytest.raises(ValueError, match="must not be nil"):
        validate_financial_resource_id(UUID(int=0))


def test_validator_rejects_non_v4_uuid() -> None:
    deterministic = uuid5(NAMESPACE_DNS, "synthetic.example")

    assert deterministic.version == 5
    with pytest.raises(ValueError, match="RFC 4122 UUID v4"):
        validate_financial_resource_id(deterministic)


def test_validator_rejects_non_rfc_variant() -> None:
    non_rfc = UUID("00000000-0000-4000-c000-000000000001")

    assert non_rfc.version is None
    with pytest.raises(ValueError, match="RFC 4122 UUID v4"):
        validate_financial_resource_id(non_rfc)
