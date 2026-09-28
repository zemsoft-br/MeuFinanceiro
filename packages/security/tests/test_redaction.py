from __future__ import annotations

import logging
import sys

from meufinanceiro_security.redaction import (
    REDACTED,
    RedactingFilter,
    install_log_redaction,
    redact,
    redact_text,
)


def test_structural_redaction_hides_sensitive_values() -> None:
    source = {
        "username": "alice",
        "password": "p@ssword",
        "nested": {"access_token": "token-value", "safe": "visible"},
    }

    sanitized = redact(source)

    assert sanitized == {
        "username": "alice",
        "password": REDACTED,
        "nested": {"access_token": REDACTED, "safe": "visible"},
    }


def test_text_redaction_hides_url_authorization_json_and_cookies() -> None:
    source = (
        "database=postgresql://alice:secret-value@postgres:5432/db "
        "Authorization: Bearer abc.def.ghi token=token-value "
        'payload={"client_secret":"json-secret"} Cookie: session=cookie-secret'
    )

    sanitized = redact_text(source)

    for secret in (
        "secret-value",
        "abc.def.ghi",
        "token-value",
        "json-secret",
        "cookie-secret",
    ):
        assert secret not in sanitized
    assert sanitized.count(REDACTED) == 5


def test_logging_filter_redacts_interpolated_arguments_and_exceptions() -> None:
    try:
        raise RuntimeError("token=exception-secret")
    except RuntimeError:
        exception_info = sys.exc_info()

    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="request password=%s",
        args=("argument-secret",),
        exc_info=exception_info,
    )

    assert RedactingFilter().filter(record) is True
    assert "argument-secret" not in record.getMessage()
    assert "exception-secret" not in (record.exc_text or "")
    assert REDACTED in record.getMessage()
    assert REDACTED in (record.exc_text or "")


def test_log_redaction_installation_is_idempotent() -> None:
    logger = logging.getLogger("meufinanceiro.tests.redaction-idempotence")
    logger.filters.clear()

    install_log_redaction()
    install_log_redaction()

    installed = [
        existing for existing in logger.filters if isinstance(existing, RedactingFilter)
    ]
    assert len(installed) == 1
