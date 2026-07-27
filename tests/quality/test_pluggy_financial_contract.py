from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from urllib.error import HTTPError
from urllib.request import Request

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "tools/pluggy-spike"
SCRIPT = SCRIPT_DIR / "pluggy_financial.py"
RUNBOOK = ROOT / "docs/spikes/PLUGGY_FINANCIAL_DATA_LAB.md"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pluggy_financial", SCRIPT)
    assert spec is not None and spec.loader is not None
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPT_DIR))


def test_financial_spike_is_documented_and_read_only() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert RUNBOOK.is_file()
    assert 'TRANSACTIONS_ENDPOINT = "/v2/transactions"' in source
    assert 'BILLS_ENDPOINT = "/bills"' in source
    assert '"POST", "/items"' not in source
    assert "requests" not in source
    assert "dotenv" not in source


def test_financial_collection_uses_cursor_transactions_and_bills() -> None:
    module = load_module()
    bank_id = "11111111-1111-4111-8111-111111111111"
    card_id = "22222222-2222-4222-8222-222222222222"
    bill_id = "33333333-3333-4333-8333-333333333333"
    calls: list[str] = []

    def transport(request: Request, timeout: float) -> bytes:
        assert timeout == 15.0
        calls.append(request.full_url)
        if request.full_url.endswith("/accounts?itemId=item-test"):
            return json.dumps(
                {
                    "results": [
                        {
                            "id": bank_id,
                            "type": "BANK",
                            "subtype": "CHECKING_ACCOUNT",
                            "name": "Conta privada",
                            "balance": 901.37,
                        },
                        {
                            "id": card_id,
                            "type": "CREDIT",
                            "subtype": "CREDIT_CARD",
                            "number": "9999",
                            "balance": 401.22,
                        },
                    ]
                }
            ).encode()
        if request.full_url.endswith(f"/v2/transactions?accountId={bank_id}"):
            return json.dumps(
                {
                    "results": [
                        {
                            "id": "44444444-4444-4444-8444-444444444444",
                            "accountId": bank_id,
                            "description": "Descrição privada A",
                            "amount": 901.37,
                            "date": "2026-01-01T00:00:00.000Z",
                            "status": "POSTED",
                            "type": "DEBIT",
                        }
                    ],
                    "next": f"?accountId={bank_id}&after=cursor-one",
                }
            ).encode()
        if request.full_url.endswith(
            f"/v2/transactions?accountId={bank_id}&after=cursor-one"
        ):
            return json.dumps(
                {
                    "results": [
                        {
                            "id": "55555555-5555-4555-8555-555555555555",
                            "accountId": bank_id,
                            "description": "Descrição privada B",
                            "amount": 402.19,
                            "date": "2026-03-15T00:00:00.000Z",
                            "status": "PENDING",
                            "type": "CREDIT",
                        }
                    ]
                }
            ).encode()
        if request.full_url.endswith(f"/v2/transactions?accountId={card_id}"):
            return json.dumps(
                {
                    "results": [
                        {
                            "id": "66666666-6666-4666-8666-666666666666",
                            "accountId": card_id,
                            "description": "Compra privada",
                            "amount": 123.45,
                            "date": "2026-04-01T00:00:00.000Z",
                            "status": "PENDING",
                            "type": "DEBIT",
                            "creditCardMetadata": {
                                "installmentNumber": 1,
                                "totalInstallments": 6,
                                "billForecastDate": "2026-05",
                            },
                        }
                    ]
                }
            ).encode()
        if request.full_url.endswith(f"/bills?accountId={card_id}"):
            return json.dumps(
                {
                    "results": [
                        {
                            "id": bill_id,
                            "dueDate": "2026-05-10T00:00:00.000Z",
                            "totalAmount": 999.99,
                            "allowsInstallments": True,
                        }
                    ]
                }
            ).encode()
        raise AssertionError(request.full_url)

    client = module.FinancialPluggyClient(
        module.Credentials("client", "secret"),
        transport=transport,
        sleeper=lambda _: None,
    )
    accounts = client.get_product("api-key", "accounts", "item-test")
    account_records = module.records(accounts)
    collections = []
    raw_payloads = [accounts]
    for ordinal, account in enumerate(account_records, start=1):
        account_id = account["id"]
        pages, truncated, cursor_observed = module.collect_transaction_pages(
            client,
            "api-key",
            account_id,
            max_pages=5,
        )
        raw_payloads.extend(pages)
        bills = None
        if account["subtype"] == "CREDIT_CARD":
            bills = client.get_bills("api-key", account_id)
            raw_payloads.append(bills)
        collections.append(
            module.FinancialAccountCollection(
                ordinal=ordinal,
                account_type=account["type"],
                account_subtype=account["subtype"],
                query_status="QUERIED",
                transaction_pages=pages,
                transactions_truncated=truncated,
                cursor_pagination_observed=cursor_observed,
                bills=bills,
            )
        )

    report = module.financial_collection_report(
        item={"status": "UPDATED", "executionStatus": "SUCCESS"},
        accounts=accounts,
        account_collections=collections,
        accounts_truncated=False,
    )
    forbidden = {
        "item-test",
        bank_id,
        card_id,
        bill_id,
        "Descrição privada A",
        "Descrição privada B",
        "Compra privada",
        "901.37",
        "402.19",
        "123.45",
        "999.99",
        "2026-01-01T00:00:00.000Z",
        "2026-03-15T00:00:00.000Z",
        "2026-04-01T00:00:00.000Z",
        "2026-05-10T00:00:00.000Z",
    }
    for payload in raw_payloads:
        forbidden.update(module.raw_forbidden_values(payload))
    rendered = module.validate_report(report, forbidden_values=tuple(sorted(forbidden)))

    assert report["accounts"]["credit_card_count"] == 1
    reports = report["accounts"]["records"]
    assert reports[0]["transactions"]["record_count"] == 2
    assert reports[0]["transactions"]["page_count"] == 2
    assert reports[0]["transactions"]["cursor_pagination_observed"]
    assert reports[0]["transactions"]["status_counts"] == {
        "PENDING": 1,
        "POSTED": 1,
    }
    assert reports[1]["transactions"]["pending_count"] == 1
    assert (
        reports[1]["transactions"]["installment_metadata"][
            "total_installments_present_count"
        ]
        == 1
    )
    assert reports[1]["bills"]["record_count"] == 1
    assert "/v2/transactions" in " ".join(calls)
    assert "/bills?" in " ".join(calls)
    for sensitive in forbidden:
        assert sensitive not in rendered


def test_financial_collection_accepts_empty_accounts() -> None:
    module = load_module()
    report = module.financial_collection_report(
        item={"status": "UPDATED", "executionStatus": "SUCCESS"},
        accounts={"results": []},
        account_collections=[],
        accounts_truncated=False,
    )
    assert report["accounts"]["inventory"]["record_count"] == 0
    assert report["accounts"]["queried_count"] == 0
    assert report["accounts"]["credit_card_count"] == 0
    module.validate_report(report)


def test_transaction_cursor_rejects_external_or_wrong_account() -> None:
    module = load_module()
    account_id = "11111111-1111-4111-8111-111111111111"
    with pytest.raises(module.SpikeError, match="Cursor de transações inválido"):
        module.next_transaction_path(
            "https://evil.example/v2/transactions?accountId=" + account_id,
            account_id,
        )
    with pytest.raises(
        module.SpikeError,
        match="Cursor de transações não corresponde à conta",
    ):
        module.next_transaction_path(
            "?accountId=22222222-2222-4222-8222-222222222222&after=x",
            account_id,
        )


def test_transaction_pagination_is_bounded() -> None:
    module = load_module()
    account_id = "11111111-1111-4111-8111-111111111111"
    calls = 0

    def transport(request: Request, timeout: float) -> bytes:
        nonlocal calls
        del request, timeout
        calls += 1
        return json.dumps(
            {
                "results": [],
                "next": f"?accountId={account_id}&after={calls}",
            }
        ).encode()

    client = module.FinancialPluggyClient(
        module.Credentials("client", "secret"), transport=transport
    )
    pages, truncated, cursor_observed = module.collect_transaction_pages(
        client, "api-key", account_id, max_pages=3
    )
    assert len(pages) == 3
    assert calls == 3
    assert truncated
    assert cursor_observed


def test_financial_collection_limits_are_validated() -> None:
    module = load_module()
    module.validate_collection_limit(1, "--max-pages", 20)
    module.validate_collection_limit(20, "--max-pages", 20)
    with pytest.raises(module.SpikeError, match="entre 1 e 20"):
        module.validate_collection_limit(0, "--max-pages", 20)
    with pytest.raises(module.SpikeError, match="entre 1 e 20"):
        module.validate_collection_limit(21, "--max-pages", 20)


def test_financial_validation_avoids_substring_false_positives() -> None:
    module = load_module()
    report = {
        "created_at_utc": "2026-07-27T16:30:00+00:00",
        "count": 3,
        "privacy": {"financial_values_persisted": False},
    }

    rendered = module.validate_financial_report(
        report,
        forbidden_substrings=(),
        forbidden_raw_scalars=("2026", "30"),
    )
    assert "2026-07-27" in rendered

    with pytest.raises(module.SpikeError, match="Valor sensível detectado"):
        module.validate_financial_report(
            {"unexpected_scalar": "2026"},
            forbidden_substrings=(),
            forbidden_raw_scalars=("2026",),
        )


def test_financial_validation_keeps_credential_substring_protection() -> None:
    module = load_module()
    with pytest.raises(module.SpikeError, match="Valor sensível detectado"):
        module.validate_financial_report(
            {"unexpected_scalar": "prefix-local-secret-suffix"},
            forbidden_substrings=("local-secret",),
            forbidden_raw_scalars=(),
        )


def test_financial_script_type_checks_strictly() -> None:
    if importlib.util.find_spec("mypy") is None:
        pytest.skip("mypy is installed by the mandatory quality environment")
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", str(SCRIPT)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_account_collection_records_product_http_404_without_aborting() -> None:
    module = load_module()
    account_id = "11111111-1111-4111-8111-111111111111"
    calls: list[str] = []

    def transport(request: Request, timeout: float) -> bytes:
        del timeout
        calls.append(request.full_url)
        raise HTTPError(request.full_url, 404, "Not Found", hdrs=None, fp=None)

    client = module.FinancialPluggyClient(
        module.Credentials("client", "secret"),
        transport=transport,
        sleeper=lambda _: None,
    )
    collection = module.collect_account_financial_data(
        client,
        "api-key",
        account_id,
        ordinal=1,
        account_type="CREDIT",
        account_subtype="CREDIT_CARD",
        max_pages=5,
    )

    assert collection.query_status == ("TRANSACTIONS_AND_BILLS_NOT_AVAILABLE_HTTP_404")
    assert collection.transaction_pages == ()
    assert collection.bills is None
    assert len(calls) == 2

    report = module.financial_collection_report(
        item={"status": "UPDATED", "executionStatus": "SUCCESS"},
        accounts={
            "results": [
                {
                    "id": account_id,
                    "type": "CREDIT",
                    "subtype": "CREDIT_CARD",
                }
            ]
        },
        account_collections=[collection],
        accounts_truncated=False,
    )
    account_report = report["accounts"]["records"][0]
    assert account_report["transactions"]["query_status"] == ("NOT_AVAILABLE_HTTP_404")
    assert account_report["bills"]["query_status"] == "NOT_AVAILABLE_HTTP_404"
    module.validate_report(report, forbidden_values=(account_id,))


def test_account_collection_does_not_swallow_other_http_errors() -> None:
    module = load_module()
    account_id = "11111111-1111-4111-8111-111111111111"

    def transport(request: Request, timeout: float) -> bytes:
        del timeout
        raise HTTPError(request.full_url, 500, "Error", hdrs=None, fp=None)

    client = module.FinancialPluggyClient(
        module.Credentials("client", "secret"),
        transport=transport,
        sleeper=lambda _: None,
    )
    with pytest.raises(module.SpikeError, match="HTTP 500"):
        module.collect_account_financial_data(
            client,
            "api-key",
            account_id,
            ordinal=1,
            account_type="BANK",
            account_subtype="CHECKING_ACCOUNT",
            max_pages=5,
        )
