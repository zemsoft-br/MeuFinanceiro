from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "packages/persistence/src/meufinanceiro_persistence/demo_contract.py"
DATA = ROOT / "packages/persistence/src/meufinanceiro_persistence/demo_finance_data.py"
FIXTURE = ROOT / "packages/persistence/src/meufinanceiro_persistence/demo_financial_fixture.py"
STORE = ROOT / "packages/persistence/src/meufinanceiro_persistence/demo.py"
CLI = ROOT / "packages/persistence/src/meufinanceiro_persistence/demo_cli.py"
COMPOSE = ROOT / "compose.yaml"
API = ROOT / "apps/api/app/api/routes/demo.py"


def test_demo_finance_contract_is_versioned_and_deterministic() -> None:
    contract = CONTRACT.read_text(encoding="utf-8")
    data = DATA.read_text(encoding="utf-8")

    assert "DEMO_FIXTURE_VERSION: Final = 2" in contract
    assert 'DEMO_SCOPE: Final = "finance_phase1"' in contract
    assert "date(2026, 11, 1)" in contract
    assert "4979.25" in contract
    assert "uuid4(" not in contract + data
    assert 'role="REVERSAL"' in data
    assert "reversal_of_id=_REVERSED_EXPENSE_ID" in data


def test_load_is_runtime_scoped_and_reset_is_separately_scoped() -> None:
    fixture = FIXTURE.read_text(encoding="utf-8")
    store = STORE.read_text(encoding="utf-8")
    cli = CLI.read_text(encoding="utf-8")
    compose = COMPOSE.read_text(encoding="utf-8")

    assert "func.set_config(" in fixture
    assert "on_conflict_do_nothing()" in fixture
    assert "on_conflict_do_update" not in fixture + store
    assert "self._reset_engine = reset_engine" in store
    assert "reset_engine or engine" not in store
    assert "_require_reset_engine" in store
    assert "admin_database_url" in cli
    assert "ADMIN_DATABASE_URL:" in compose
    assert "DATABASE_URL:" in compose


def test_fixture_is_provider_neutral_and_has_no_balance_column() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (CONTRACT, DATA, FIXTURE, STORE, CLI)
    ).lower()

    assert "pluggy" not in combined
    assert "httpx" not in combined
    assert "requests." not in combined
    assert "float(" not in combined
    assert "balance = column" not in combined
    assert "balance = mapped_column" not in combined


def test_demo_status_exposes_read_only_finance_scope() -> None:
    api = API.read_text(encoding="utf-8")

    assert 'Literal["finance_phase1"]' in api
    assert '@router.get("/status"' in api
    assert "@router.post" not in api
    assert "@router.delete" not in api
