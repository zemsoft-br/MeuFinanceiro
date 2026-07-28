from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADR = (
    ROOT / "docs/adr/0012-banking-integration-persistence-security-and-feature-flag.md"
)
MODEL = ROOT / "docs/architecture/BANKING_INTEGRATION_PERSISTENCE_MODEL.md"
ADR_INDEX = ROOT / "docs/adr/README.md"


def read(path: Path) -> str:
    assert path.is_file()
    return path.read_text(encoding="utf-8")


def combined_contract() -> str:
    return "\n".join((read(ADR), read(MODEL)))


def test_adr_is_accepted_and_implementation_remains_out_of_scope() -> None:
    adr = read(ADR)
    model = read(MODEL)

    assert "# ADR-0012" in adr
    assert "- Status: Accepted" in adr
    assert "Issue: #64" in adr
    assert "Este ADR não cria tabelas ou migrations" in adr
    assert "não cria migration" in model
    assert "modelos SQLAlchemy" in model
    assert "chamadas externas" in model


def test_integration_is_fail_closed_and_disabled_by_default() -> None:
    content = combined_contract()

    for state in ("disabled", "configured", "enabled"):
        assert state in content

    assert "A ausência de uma configuração ativa significa `disabled`" in content
    assert "não instancia" in content
    assert "Configurar e" in content
    assert "ativar são ações distintas" in content
    assert "health principal permanece saudável" in content
    assert "funcionamento integral sem provider" in content


def test_application_credentials_use_context_bound_envelopes() -> None:
    content = combined_contract()

    assert "AES-256-GCM" in content
    assert "AAD canônico" in content
    for component in (
        "installation:{installation_id}",
        "provider:{provider}",
        "configuration:{configuration_id}",
        "field:{field_name}",
    ):
        assert component in content

    assert "client_id_envelope" in content
    assert "client_secret_envelope" in content
    assert "Mover um envelope" in content
    assert "deve falhar" in content


def test_ephemeral_and_banking_credentials_are_never_persisted() -> None:
    content = combined_contract()

    assert "A API key e o Connect Token nunca são persistidos" in content
    assert "Senha bancária e MFA nunca são" in content
    assert "retenção zero" in content
    assert "resposta HTTP bruta" in content
    assert "headers de autenticação" in content
    assert "mensagem livre do provider" in content


def test_residence_entities_require_direct_rls_scope() -> None:
    content = combined_contract()

    assert "representam conexão, conta, cursor, execução ou dado de uma família" in content
    assert "`residence_id` diretamente" in content
    assert "RLS obrigatória" in content
    assert "não pode possuir `BYPASSRLS`" in content
    assert "própria linha" in content
    assert "duas residências" in content
    assert "impedir leitura, update e delete cruzados" in content
    assert "FKs compostas" in content


def test_conceptual_schema_has_minimum_entities() -> None:
    content = combined_contract()

    for table in (
        "provider_configurations",
        "connections",
        "connection_capabilities",
        "sync_runs",
        "sync_cursors",
        "external_accounts",
        "external_observations",
        "audit_events",
    ):
        assert table in content

    assert "O schema futuro chama-se `integrations`" in content


def test_connection_and_sync_uniqueness_are_explicit() -> None:
    content = combined_contract()

    assert "UNIQUE (installation_id, provider, external_connection_id)" in content
    assert "UNIQUE (connection_id, capability)" in content
    assert "UNIQUE (connection_id, idempotency_key)" in content
    assert "somente uma execução externa ativa por conexão" in content
    assert "cursor de uma conta não pode ser usado em outra" in content


def test_retention_separates_secrets_operations_and_domain_data() -> None:
    content = combined_contract()

    assert "execuções de sincronização: padrão de 90 dias" in content
    assert "eventos administrativos e de segurança: padrão de 365 dias" in content
    assert "tokens efêmeros e credenciais bancárias | nunca persistir" in content
    assert "dados financeiros importados" in content
    assert "não apaga automaticamente o" in content
    assert "histórico financeiro" in content
    assert "nunca usa cascade destrutivo" in content


def test_rewrap_is_transactional_verifiable_and_separate_from_key_removal() -> None:
    content = combined_contract()

    assert "Rewrap transacional" in content
    assert "atualizar envelope e revisão na mesma transação" in content
    assert "Falha em qualquer linha preserva o envelope anterior" in content
    assert "zero envelopes referenciam a chave antiga" in content
    assert "Não é parte automática do rewrap" in content
    assert "confirmação administrativa explícita" in content


def test_backup_restore_requires_database_and_keyring() -> None:
    content = combined_contract()

    assert "snapshot do PostgreSQL" in content
    assert "keyring correspondente" in content
    assert "Restaurar somente o banco ou somente o keyring" in content
    assert "referenced_key_ids" in content
    assert "nenhum plaintext é impresso" in content
    assert "provider permanece `disabled`" in content


def test_observability_has_low_cardinality_and_no_sensitive_labels() -> None:
    model = read(MODEL)

    assert "Métricas permitidas" in model
    assert "Labels proibidos" in model
    for label in (
        "residência",
        "external ID",
        "cursor",
        "documento",
        "descrição",
        "valor",
        "token",
    ):
        assert label in model

    assert "IDs internos, categoria neutra, contagens e duração" in model
    assert "redaction da fundação permanece obrigatório" in model


def test_documents_do_not_embed_real_tokens_or_external_identifiers() -> None:
    content = combined_contract()

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


def test_follow_up_work_is_split_into_isolated_issues() -> None:
    model = read(MODEL)

    assert "## Próximas issues obrigatórias" in model
    assert "### Interface executável" in model
    assert "### Migration do schema `integrations`" in model
    assert "### Configuração administrativa" in model
    assert "### Adaptador Pluggy mínimo" in model
    assert "provider fake" in model
    assert "nenhum SDK Pluggy" in model


def test_adr_index_links_the_accepted_decision() -> None:
    index = read(ADR_INDEX)

    assert "0012-banking-integration-persistence-security-and-feature-flag.md" in index
    assert "ADR-0012" in index
