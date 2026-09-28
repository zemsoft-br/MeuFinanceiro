from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PERSISTENCE = ROOT / "packages/persistence/src/meufinanceiro_persistence"
CLEANUP = (PERSISTENCE / "demo_transfer_cleanup.py").read_text(encoding="utf-8")
STORE = (PERSISTENCE / "demo.py").read_text(encoding="utf-8")


def test_demo_reset_orders_transfer_cleanup_before_financial_cleanup() -> None:
    assert "DEMO_INSTALLATION_ID" in CLEANUP
    assert "DEMO_RESIDENCE_ID" in CLEANUP
    assert "financial_transfer_legs" in CLEANUP
    assert 'role == "REVERSAL"' in CLEANUP
    assert STORE.index("reset_demo_transfers(connection)") < STORE.index(
        "reset_demo_financial_fixture(connection)"
    )
