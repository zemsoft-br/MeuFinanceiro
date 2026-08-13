from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOMAIN = ROOT / "packages/finance/src/meufinanceiro_finance/balance_statement.py"
QUERY = ROOT / "packages/persistence/src/meufinanceiro_persistence/financial_balance_query.py"


def test_balance_derivation_is_read_only_and_provider_neutral() -> None:
    domain = DOMAIN.read_text(encoding="utf-8")
    query = QUERY.read_text(encoding="utf-8")
    combined = domain + query

    assert "Decimal(\"0\")" in domain
    assert "effective_date" in domain
    assert "created_at" in domain
    assert "movement.id.int" in domain
    assert "opening_balance is not None" in domain
    assert "list_movements" in query
    assert "get_opening_balance" in query
    assert "get_account" in query

    for forbidden in (
        "float(",
        "sqlalchemy",
        "pluggy",
        "requests.",
        "httpx",
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "balance = Column",
        "balance = mapped_column",
    ):
        assert forbidden not in combined


def test_statement_does_not_invent_opening_movement() -> None:
    domain = DOMAIN.read_text(encoding="utf-8")

    assert "FinancialStatementEntry(movement=movement" not in domain
    assert "opening_money =" in domain
    assert "entries=tuple(entries)" in domain
