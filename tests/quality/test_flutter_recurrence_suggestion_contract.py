from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE = ROOT / "apps/app/lib/features/finance"
API = (FINANCE / "financial_recurrence_suggestion_api.dart").read_text(encoding="utf-8")
SECTION = (FINANCE / "financial_recurrence_suggestions_section.dart").read_text(
    encoding="utf-8"
)
DIALOG = (FINANCE / "financial_recurrence_suggestion_review_dialog.dart").read_text(
    encoding="utf-8"
)
CONTROLLER = (FINANCE / "financial_recurrence_controller.dart").read_text(
    encoding="utf-8"
)
SCREEN = (FINANCE / "financial_recurrence_screen.dart").read_text(encoding="utf-8")
POLICY = (FINANCE / "financial_recurrence_policy.dart").read_text(encoding="utf-8")
CORE_API = (FINANCE / "financial_core_api.dart").read_text(encoding="utf-8")
CLIENT_FILES = {
    "api": API,
    "section": SECTION,
    "dialog": DIALOG,
}


def _code(source: str) -> str:
    return re.sub(r"(?m)^\s*//.*$", "", source)


def _method(source: str, name: str) -> str:
    start = source.index(f"Future<FinancialRecurrenceActionResult> {name}(")
    following = re.search(
        r"\n  (?:Future<[\w<>?, ]+>|bool|void|FinancialRecurrenceActionResult) \w+\(",
        source[start + 20 :],
    )
    end = start + 20 + following.start() if following else len(source)
    return source[start:end]


def test_money_is_never_floating_point_in_the_suggestion_client() -> None:
    for name, source in CLIENT_FILES.items():
        code = _code(source)
        assert "toDouble" not in code and "parseDouble" not in code, name
        assert "double.parse" not in code and "double.tryParse" not in code, name
        assert not re.search(r"\bdouble\b", code), name
        assert not re.search(r"\bnum\b", code), name


def test_the_client_detects_nothing_and_owns_no_calendar_or_balance_rule() -> None:
    for name, source in CLIENT_FILES.items():
        code = _code(source)
        for forbidden in (
            "BigInt",
            "fold(",
            "reduce(",
            "daysInMonth",
            "lastDay",
            "Duration(days",
            ".add(Duration",
            "DateTime.now",
            "sha256",
            "crypto",
            "toLowerCase",
            "balance",
            "pluggy",
            "merchant",
            "provider",
            "createMovement",
        ):
            assert forbidden.lower() not in code.lower(), (name, forbidden)
    # The default start date is a plain next-month string, never a calendar rule.
    assert "financialSuggestionDefaultStartDate" in DIALOG


def test_requests_are_exactly_the_three_suggestion_endpoints() -> None:
    code = _code(API)
    assert code.count("client.get(") == 1
    assert code.count("client.post(") == 2
    for verb in ("client.put(", "client.patch(", "client.delete("):
        assert verb not in code
    for path in (
        "'finance/recurrence-suggestions'",
        "'finance/recurrence-suggestions/$id/dismiss'",
        "'finance/recurrence-suggestions/${input.fingerprint}/accept'",
    ):
        assert path in code, path
    assert "part 'financial_recurrence_suggestion_api.dart';" in CORE_API


def test_an_acceptance_sends_only_the_reviewed_fields() -> None:
    code = _code(API)
    body = code[code.index("Map<String, Object?> toJson()") :]
    body = body[: body.index("};")]
    keys = set(re.findall(r"'(\w+)':", body))
    assert keys == {
        "idempotencyKey",
        "description",
        "expectedAmount",
        "startDate",
        "dayOfMonth",
        "endDate",
    }
    for forbidden in ("accountId", "currency", "resultEffect", "fingerprint"):
        assert forbidden not in body, forbidden


def test_every_answer_is_validated_against_the_request_and_never_trusted() -> None:
    code = _code(API)
    for check in (
        "_strictJsonObject(",
        "_strictMap(",
        "suggestion accept response mismatch",
        "suggestion decision mismatch",
        "suggestion evidence is inconsistent",
        "suggestion amounts are inconsistent",
        "reasonCodes is inconsistent",
    ):
        assert check in code, check


def test_writes_are_sent_once_and_the_screen_is_read_again_never_patched() -> None:
    code = _code(CONTROLLER)
    for method in ("acceptSuggestion", "dismissSuggestion"):
        body = _method(code, method)
        assert "_write(" in body, method
        for forbidden in (
            "Timer",
            "Future.delayed",
            "while (",
            "for (",
            "retry",
            "suggestions.remove",
            "suggestions =",
        ):
            assert forbidden not in body, (method, forbidden)
    for forbidden in ("suggestions.remove", "suggestions.removeWhere"):
        assert forbidden not in code, forbidden
    # No local patching of the suggestions: only the canonical re-read sets them.
    assert not re.search(r"(?<!this)\.suggestions\s*=[^=]", code)
    assert code.count(".acceptRecurrenceSuggestion(") == 1
    assert code.count(".dismissRecurrenceSuggestion(") == 1
    assert code.count(".listRecurrenceSuggestions()") == 1
    # An ambiguous accept keeps its key only for an explicit identical retry.
    assert "_acceptKeys[attempt] ?? input.idempotencyKey" in code
    # Only access failures fail the screen; anything else marks the section.
    assert "suggestionsUnavailable" in code


def test_the_screen_reviews_before_creating_and_confirms_before_dismissing() -> None:
    code = _code(SCREEN)
    create = code[code.index("_createFromSuggestion(") :]
    create = create[: create.index("Future<void> _dismissSuggestion")]
    assert "FinancialRecurrenceSuggestionReviewDialog(" in create
    assert create.index("showDialog") < create.index(".acceptSuggestion(")
    assert "if (input == null || !mounted) return;" in create
    dismiss = code[code.index("Future<void> _dismissSuggestion") :]
    dismiss = dismiss[: dismiss.index("Future<void> _skip")]
    assert "dismissConfirmKey" in dismiss and "dismissCancelKey" in dismiss
    assert dismiss.index("showDialog") < dismiss.index(".dismissSuggestion(")
    assert "if (confirmed != true || !mounted) return;" in dismiss


def test_the_section_states_the_notice_and_gates_actions_by_owner_and_state() -> None:
    code = _code(SECTION)
    assert "financialRecurrenceSuggestionNotice" in code
    assert "Nenhum padrão mensal detectado" in code
    assert "suggestionsUnavailable" in code
    assert "if (item.canAccept)" in code
    assert "onPressed: writable ? onCreate : null" in code
    assert "onPressed: writable ? onDismiss : null" in code
    assert "Detectamos um padrão; nada será criado sem sua confirmação." in _code(
        POLICY
    )
    for reason in (
        "exactDescription",
        "consecutiveMonths",
        "onePerMonth",
        "dayWindow",
        "amountFixed",
        "amountVariable",
    ):
        assert f"FinancialSuggestionReason.{reason}" in _code(POLICY), reason
