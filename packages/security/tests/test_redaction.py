from __future__ import annotations

import logging

from meufinanceiro_security.redaction import (
    REDACTED,
    RedactingFilter,
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


def test_text_redaction_hides_url_and_authorization_credentials() -> None:
    source = (
        "database=postgresql://alice:secret-value@postgres:5432/db "
        "Authorization: Bearer abc.def.ghi token=token-value"
    )

    sanitized = redact_text(source)

    assert "secret-value" not in sanitized
    assert "abc.def.ghi" not in sanitized
    assert "token-value" not in sanitized
    assert sanitized.count(REDACTED) == 3


def test_logging_filter_redacts_arguments_and_exceptions() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="request password=%s",
        args=("secret-value",),
        exc_info=None,
    )

    assert RedactingFilter().filter(record) is True
    assert "secret-value" not in record.getMessage()
    assert REDACTED in record.getMessage()
