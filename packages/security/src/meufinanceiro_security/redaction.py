"""Structural and textual redaction for logs, errors, and diagnostics."""

from __future__ import annotations

import logging
import re
import traceback
from collections.abc import Mapping, Sequence
from typing import Any

REDACTED = "[REDACTED]"
SENSITIVE_KEYS = (
    r"password|passwd|pwd|token|authorization|cookie|api[_-]?key|client[_-]?secret|"
    r"master[_-]?key|key[_-]?material|database[_-]?url|connection[_-]?string"
)
SENSITIVE_KEY_PATTERN = re.compile(rf"(?:{SENSITIVE_KEYS})", re.IGNORECASE)
URL_CREDENTIAL_PATTERN = re.compile(
    r"(?P<prefix>[A-Za-z][A-Za-z0-9+.-]*://[^:/\s@]+:)(?P<secret>[^@\s]+)(?P<suffix>@)"
)
AUTHORIZATION_PATTERN = re.compile(
    r"(?P<prefix>\b(?:Bearer|Basic)\s+)(?P<secret>[A-Za-z0-9._~+/=-]+)",
    re.IGNORECASE,
)
COOKIE_PATTERN = re.compile(
    r"(?P<prefix>\b(?:Cookie|Set-Cookie)\s*:\s*)(?P<secret>[^\r\n]+)",
    re.IGNORECASE,
)
JSON_ASSIGNMENT_PATTERN = re.compile(
    rf'(?P<prefix>"(?:{SENSITIVE_KEYS})"\s*:\s*")(?P<secret>(?:\\.|[^"])*)"',
    re.IGNORECASE,
)
ASSIGNMENT_PATTERN = re.compile(
    r"(?P<key>password|passwd|pwd|token|api[_-]?key|client[_-]?secret|master[_-]?key)"
    r"(?P<separator>\s*[:=]\s*)(?P<secret>[^\s,;]+)",
    re.IGNORECASE,
)


def redact_text(value: str) -> str:
    redacted = URL_CREDENTIAL_PATTERN.sub(
        lambda match: f"{match.group('prefix')}{REDACTED}{match.group('suffix')}",
        value,
    )
    redacted = AUTHORIZATION_PATTERN.sub(
        lambda match: f"{match.group('prefix')}{REDACTED}",
        redacted,
    )
    redacted = COOKIE_PATTERN.sub(
        lambda match: f"{match.group('prefix')}{REDACTED}",
        redacted,
    )
    redacted = JSON_ASSIGNMENT_PATTERN.sub(
        lambda match: f'{match.group("prefix")}{REDACTED}"',
        redacted,
    )
    return ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group('key')}{match.group('separator')}{REDACTED}",
        redacted,
    )


def redact(value: Any, *, key: str | None = None) -> Any:
    if key is not None and SENSITIVE_KEY_PATTERN.search(key):
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, bytes):
        return REDACTED
    if isinstance(value, Mapping):
        return {
            str(item_key): redact(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, Sequence):
        return [redact(item) for item in value]
    return value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.getMessage())
        record.args = ()
        if record.exc_info:
            formatted = "".join(traceback.format_exception(*record.exc_info))
            record.exc_text = redact_text(formatted)
            record.exc_info = None
        return True


def _ensure_filter(target: logging.Filterer) -> None:
    if not any(isinstance(existing, RedactingFilter) for existing in target.filters):
        target.addFilter(RedactingFilter())


def install_log_redaction() -> None:
    root = logging.getLogger()
    _ensure_filter(root)
    for handler in root.handlers:
        _ensure_filter(handler)
    for candidate in logging.Logger.manager.loggerDict.values():
        if isinstance(candidate, logging.Logger):
            _ensure_filter(candidate)
            for handler in candidate.handlers:
                _ensure_filter(handler)
