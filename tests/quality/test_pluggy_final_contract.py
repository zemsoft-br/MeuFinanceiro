from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs/architecture/BANKING_PROVIDER_CONTRACT.md"
FINAL_REPORT = ROOT / "docs/spikes/PLUGGY_FINAL_REPORT.md"
SPIKE_README = ROOT / "tools/pluggy-spike/README.md"


def read(path: Path) -> str:
    assert path.is_file()
    return path.read_text(encoding="utf-8")


def test_banking_provider_contract_is_validated_but_not_implemented() -> None:
    contract = read(CONTRACT)

    assert "Status: **validado para implementação futura**" in contract
    assert "Não existe implementação produtiva" in contract
    assert "O sistema deve operar integralmente sem provedor bancário" in contract
    assert "O provedor nunca inicia pagamentos, DDA ou transferências" in contract
    assert "Nenhum objeto Pluggy é retornado pelo contrato neutro" in contract


def test_contract_separates_security_and_lifecycle_concepts() -> None:
    contract = read(CONTRACT)

    for concept in (
        "### Application",
        "### API key",
        "### Connect Token",
        "### ExternalConnection",
        "### Consentimento",
        "### Execução de sincronização",
    ):
        assert concept in contract

    assert "API key" in contract
    assert "Connect Token" in contract
    assert "somente memória" in contract
    assert "nova conexão para renovar consentimento é proibido" in contract
    assert "Desconectar é uma operação destrutiva" in contract


def test_capabilities_are_declared_per_connection() -> None:
    contract = read(CONTRACT)

    assert "Capacidades são declaradas por conexão" in contract
    for capability in (
        "bank_accounts",
        "credit_accounts",
        "transactions",
        "credit_card_bills",
        "investments",
        "loans",
        "manual_refresh",
        "consent_renewal",
        "disconnect",
        "webhooks",
    ):
        assert capability in contract

    for state in (
        "SUPPORTED",
        "NOT_AVAILABLE",
        "REQUIRES_USER_ACTION",
        "NOT_OBSERVED",
        "UNKNOWN",
    ):
        assert state in contract


def test_manual_sync_is_bounded_and_webhook_optional() -> None:
    contract = read(CONTRACT)

    assert "## Sincronização manual sem webhook obrigatório" in contract
    assert "A primeira implementação produtiva deve suportar sincronização manual" in contract
    assert "de endpoint público" in contract
    assert "Somente uma atualização pode permanecer ativa por conexão" in contract
    assert "Não existe polling contínuo" in contract
    assert "Ausência de informação segura bloqueia" in contract
    assert "Webhooks podem reduzir polling" in contract
    assert "O modo local permanece funcional sem URL pública" in contract
    assert "nunca depender somente do webhook" in contract


def test_reconciliation_contract_preserves_pending_and_deletions() -> None:
    contract = read(CONTRACT)

    for state in ("CONFIRMED", "PENDING", "INFERRED", "DELETED"):
        assert state in contract

    assert "repetir a mesma página não cria novos lançamentos" in contract
    assert "mudança de `PENDING` para `CONFIRMED` atualiza" in contract
    assert "exclusão externa marca a representação importada para revisão" in contract
    assert "lançamento do usuário silenciosamente" in contract
    assert "não pode depender apenas de descrição, data e valor" in contract


def test_retry_policy_remains_bounded() -> None:
    contract = read(CONTRACT)

    assert "`401/403`: renovar API key uma vez" in contract
    assert "`429`: respeitar `RateLimit-Reset` ou `Retry-After`" in contract
    assert "no máximo três tentativas" in contract
    assert "`400/404` funcionais: sem retry automático" in contract
    assert "não promete dados em tempo real" in contract


def test_final_report_consolidates_all_spike_deliveries() -> None:
    report = read(FINAL_REPORT)

    assert "conclusão técnica da issue #11" in report
    for reference in ("PR #54", "PR #56", "PR #58", "PR #60", "issue #61"):
        assert reference in report

    assert "392 transações" in report
    assert "357 transações `POSTED`" in report
    assert "35 transações `PENDING`" in report
    assert "cinco faturas" in report
    assert "20 transações com metadados de parcelas" in report
    assert "zero investimentos e zero empréstimos" in report


def test_final_report_keeps_facts_inferences_and_gaps_separate() -> None:
    report = read(FINAL_REPORT)

    assert "### Fatos comprovados" in report
    assert "### Inferências arquiteturais aceitas" in report
    assert "### Lacunas deliberadas" in report
    assert "Nenhuma dessas lacunas justifica operação destrutiva" in report


def test_threat_model_and_data_classification_are_explicit() -> None:
    contract = read(CONTRACT)
    report = read(FINAL_REPORT)

    for content in (contract, report):
        assert "Threat model" in content
        assert "single-flight" in content
        assert "cursor opaco" in content
        assert "delete silencioso" in content
        assert "keyring" in content

    assert "| payload bruto | resposta HTTP completa | proibido |" in report
    assert "| segredo efêmero | API key, Connect Token | somente memória |" in report


def test_final_report_does_not_embed_real_credentials_or_identifiers() -> None:
    content = "\n".join((read(CONTRACT), read(FINAL_REPORT), read(SPIKE_README)))

    assert "client-secret-secret" not in content
    assert "api-key-secret" not in content
    assert "connect-token-secret" not in content
    assert not re.search(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
        content,
        flags=re.IGNORECASE,
    )
    assert not re.search(
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."
        r"[A-Za-z0-9_-]{10,}\b",
        content,
    )


def test_spike_readme_points_to_all_canonical_documents() -> None:
    readme = read(SPIKE_README)

    for path in (
        "PLUGGY_SANDBOX_LAB.md",
        "PLUGGY_FINANCIAL_DATA_LAB.md",
        "PLUGGY_AUTH_LIFECYCLE_LAB.md",
        "PLUGGY_FINAL_REPORT.md",
        "BANKING_PROVIDER_CONTRACT.md",
    ):
        assert path in readme

    assert "A spike foi concluída tecnicamente" in readme
    assert "sem reutilizar os scripts como runtime" in readme


def test_sources_cover_lifecycle_limits_transactions_and_consent() -> None:
    contract = read(CONTRACT)

    for source in (
        "docs/item-lifecycle",
        "docs/updating-an-item",
        "docs/consents",
        "docs/consent-management-delete-an-item",
        "docs/webhooks",
        "docs/rate-limits",
        "docs/rate-limits-of",
        "docs/transactions",
        "reference/transactions-list-by-cursor",
    ):
        assert source in contract
