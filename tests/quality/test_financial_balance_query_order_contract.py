from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUERY = (
    ROOT
    / "packages/persistence/src/meufinanceiro_persistence/financial_balance_query.py"
)


def test_account_is_resolved_before_derived_inputs() -> None:
    source = QUERY.read_text(encoding="utf-8")

    account_read = source.index("self._account_store.get_account(")
    opening_read = source.index("self._opening_balance_store.get_opening_balance(")
    movement_read = source.index("self._movement_store.list_movements(")

    assert account_read < opening_read < movement_read


def test_query_does_not_silently_replace_store_failures() -> None:
    source = QUERY.read_text(encoding="utf-8")

    assert "except" not in source
    assert "opening_balance = None" not in source
    assert "movements = ()" not in source
    assert 'Decimal("0")' not in source
