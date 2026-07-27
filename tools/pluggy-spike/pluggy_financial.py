#!/usr/bin/env python3
"""Sanitized Pluggy laboratory for transactions, cards, and bills.

This companion tool extends the disposable Pluggy spike without integrating the
provider into the MeuFinanceiro runtime. External identifiers stay in memory and
reports contain only schemas, counts, bounded status values, and coarse temporal
aggregates.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from pluggy_spike import (
    Credentials,
    JsonValue,
    PluggyClient,
    SpikeError,
    credentials_from_environment,
    default_report_path,
    local_output_path,
    resolve_api_base,
    validate_report,
    write_report,
)

__all__ = ["Credentials", "validate_report"]

TRANSACTIONS_ENDPOINT = "/v2/transactions"
BILLS_ENDPOINT = "/bills"
HTTP_NOT_FOUND_MESSAGE = "Pluggy respondeu HTTP 404."
MAX_FINANCIAL_ACCOUNTS = 25
MAX_TRANSACTION_PAGES = 20
SAFE_ENUM_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
ISO_DATETIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}(?:T|$)")
RAW_SENSITIVE_VALUE_KEY_PATTERN = re.compile(
    r"(?i)(^id$|id$|description|merchant|owner|name|number|tax|document|"
    r"amount|balance|date|createdat|updatedat|providerid|billid)"
)


@dataclass(frozen=True)
class FinancialAccountCollection:
    """Sanitized inputs collected for one account ordinal."""

    ordinal: int
    account_type: str | None
    account_subtype: str | None
    query_status: str
    transaction_pages: tuple[JsonValue, ...]
    transactions_truncated: bool
    cursor_pagination_observed: bool
    bills: JsonValue | None


class FinancialPluggyClient(PluggyClient):
    """Read-only endpoints required by the issue #57 laboratory."""

    def get_transactions_page(
        self,
        api_key: str,
        account_id: str,
        *,
        path: str | None = None,
    ) -> JsonValue:
        request_path = path or (
            f"{TRANSACTIONS_ENDPOINT}?{urlencode({'accountId': account_id})}"
        )
        return self._request_json("GET", request_path, api_key=api_key)

    def get_bills(self, api_key: str, account_id: str) -> JsonValue:
        query = urlencode({"accountId": account_id})
        return self._request_json("GET", f"{BILLS_ENDPOINT}?{query}", api_key=api_key)


def records(payload: JsonValue) -> list[dict[str, Any]]:
    """Return record objects without retaining container metadata values."""

    if isinstance(payload, list):
        return [entry for entry in payload if isinstance(entry, dict)]
    for key in ("results", "data", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [entry for entry in value if isinstance(entry, dict)]
    return [payload] if payload else []


def nested_field_names(payload: JsonValue) -> list[str]:
    """Inventory nested schema paths without copying payload values."""

    paths: set[str] = set()

    def walk(value: Any, prefix: str) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                path = f"{prefix}.{key}" if prefix else str(key)
                paths.add(path)
                walk(nested, path)
        elif isinstance(value, list):
            for nested in value:
                if isinstance(nested, (dict, list)):
                    walk(nested, prefix)

    for record in records(payload):
        walk(record, "")
    return sorted(paths)


def metadata_inventory(payload: JsonValue) -> dict[str, Any]:
    """Build a value-free inventory for a Pluggy response."""

    payload_records = records(payload)
    return {
        "record_count": len(payload_records),
        "field_names": sorted({key for record in payload_records for key in record}),
        "nested_field_names": nested_field_names(payload),
        "container_keys": sorted(payload) if isinstance(payload, dict) else [],
    }


def safe_enum(value: Any) -> str | None:
    """Allow only bounded provider enums in a report."""

    if isinstance(value, str) and SAFE_ENUM_PATTERN.fullmatch(value):
        return value
    return None


def safe_enum_counts(
    payload_records: Sequence[Mapping[str, Any]], key: str
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in payload_records:
        value = safe_enum(record.get(key))
        if value is not None:
            counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def presence_count(payload_records: Sequence[Mapping[str, Any]], key: str) -> int:
    return sum(record.get(key) is not None for record in payload_records)


def nested_presence_count(
    payload_records: Sequence[Mapping[str, Any]], parent: str, key: str
) -> int:
    total = 0
    for record in payload_records:
        nested = record.get(parent)
        if isinstance(nested, dict) and nested.get(key) is not None:
            total += 1
    return total


def nested_keys(payload_records: Sequence[Mapping[str, Any]], parent: str) -> list[str]:
    keys: set[str] = set()
    for record in payload_records:
        nested = record.get(parent)
        if isinstance(nested, dict):
            keys.update(str(key) for key in nested)
    return sorted(keys)


def parse_provider_datetime(value: Any) -> datetime | None:
    """Parse a provider timestamp only for coarse in-memory aggregation."""

    if not isinstance(value, str) or not ISO_DATETIME_PATTERN.match(value):
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def temporal_span_bucket(payload_records: Sequence[Mapping[str, Any]], key: str) -> str:
    """Return a coarse span without preserving any financial date."""

    values = [
        parsed
        for record in payload_records
        if (parsed := parse_provider_datetime(record.get(key))) is not None
    ]
    if not values:
        return "NONE"
    days = max(0, (max(values) - min(values)).days)
    if days == 0:
        return "SAME_DAY"
    if days <= 7:
        return "UP_TO_7_DAYS"
    if days <= 31:
        return "UP_TO_31_DAYS"
    if days <= 90:
        return "UP_TO_90_DAYS"
    if days <= 180:
        return "UP_TO_180_DAYS"
    if days <= 365:
        return "UP_TO_365_DAYS"
    return "OVER_365_DAYS"


def transaction_next_link(payload: JsonValue) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("next")
    return value.strip() if isinstance(value, str) and value.strip() else None


def next_transaction_path(next_link: str, account_id: str) -> str:
    """Validate that a cursor remains relative and bound to the same account."""

    candidate = next_link.strip()
    if candidate.startswith("?"):
        candidate = f"{TRANSACTIONS_ENDPOINT}{candidate}"
    parsed = urlsplit(candidate)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.fragment
        or parsed.path != TRANSACTIONS_ENDPOINT
    ):
        raise SpikeError("Cursor de transações inválido.")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if query.get("accountId") != [account_id]:
        raise SpikeError("Cursor de transações não corresponde à conta.")
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


def collect_transaction_pages(
    client: FinancialPluggyClient,
    api_key: str,
    account_id: str,
    *,
    max_pages: int,
) -> tuple[tuple[JsonValue, ...], bool, bool]:
    """Follow bounded cursor pages for one account."""

    pages: list[JsonValue] = []
    next_path: str | None = None
    cursor_observed = False
    for _ in range(max_pages):
        payload = client.get_transactions_page(api_key, account_id, path=next_path)
        pages.append(payload)
        next_link = transaction_next_link(payload)
        if next_link is None:
            return tuple(pages), False, cursor_observed
        cursor_observed = True
        next_path = next_transaction_path(next_link, account_id)
    return tuple(pages), True, cursor_observed


def is_http_not_found(error: SpikeError) -> bool:
    """Identify the sanitized 404 emitted by the shared Pluggy client."""

    return str(error) == HTTP_NOT_FOUND_MESSAGE


def collect_account_financial_data(
    client: FinancialPluggyClient,
    api_key: str,
    account_id: str,
    *,
    ordinal: int,
    account_type: str | None,
    account_subtype: str | None,
    max_pages: int,
) -> FinancialAccountCollection:
    """Collect one account while treating product-level 404 as unavailable."""

    print(f"Conta {ordinal}: consultando transações.", file=sys.stderr)
    transaction_status = "SUCCESS"
    try:
        pages, truncated, cursor_observed = collect_transaction_pages(
            client,
            api_key,
            account_id,
            max_pages=max_pages,
        )
    except SpikeError as exc:
        if not is_http_not_found(exc):
            raise
        pages = ()
        truncated = False
        cursor_observed = False
        transaction_status = "NOT_AVAILABLE_HTTP_404"
        print(
            f"Conta {ordinal}: transações indisponíveis (HTTP 404); continuando.",
            file=sys.stderr,
        )

    bills: JsonValue | None = None
    bills_status = "NOT_APPLICABLE"
    if account_type == "CREDIT" and account_subtype == "CREDIT_CARD":
        print(f"Conta {ordinal}: consultando faturas.", file=sys.stderr)
        bills_status = "SUCCESS"
        try:
            bills = client.get_bills(api_key, account_id)
        except SpikeError as exc:
            if not is_http_not_found(exc):
                raise
            bills_status = "NOT_AVAILABLE_HTTP_404"
            print(
                f"Conta {ordinal}: faturas indisponíveis (HTTP 404); continuando.",
                file=sys.stderr,
            )

    if (
        transaction_status == "NOT_AVAILABLE_HTTP_404"
        and bills_status == "NOT_AVAILABLE_HTTP_404"
    ):
        query_status = "TRANSACTIONS_AND_BILLS_NOT_AVAILABLE_HTTP_404"
    elif transaction_status == "NOT_AVAILABLE_HTTP_404":
        query_status = "TRANSACTIONS_NOT_AVAILABLE_HTTP_404"
    elif bills_status == "NOT_AVAILABLE_HTTP_404":
        query_status = "BILLS_NOT_AVAILABLE_HTTP_404"
    else:
        query_status = "QUERIED"

    return FinancialAccountCollection(
        ordinal=ordinal,
        account_type=account_type,
        account_subtype=account_subtype,
        query_status=query_status,
        transaction_pages=pages,
        transactions_truncated=truncated,
        cursor_pagination_observed=cursor_observed,
        bills=bills,
    )


def combined_records(payloads: Sequence[JsonValue]) -> list[dict[str, Any]]:
    combined: list[dict[str, Any]] = []
    for payload in payloads:
        combined.extend(records(payload))
    return combined


def transaction_pages_summary(
    pages: Sequence[JsonValue],
    *,
    truncated: bool,
    cursor_pagination_observed: bool,
) -> dict[str, Any]:
    """Summarize transaction structure without retaining transaction values."""

    transaction_records = combined_records(pages)
    status_counts = safe_enum_counts(transaction_records, "status")
    type_counts = safe_enum_counts(transaction_records, "type")
    field_names = sorted({key for record in transaction_records for key in record})
    nested_names = sorted({path for page in pages for path in nested_field_names(page)})
    return {
        "record_count": len(transaction_records),
        "page_count": len(pages),
        "truncated": truncated,
        "cursor_pagination_observed": cursor_pagination_observed,
        "field_names": field_names,
        "nested_field_names": nested_names,
        "status_counts": status_counts,
        "type_counts": type_counts,
        "pending_count": status_counts.get("PENDING", 0),
        "posted_count": status_counts.get("POSTED", 0),
        "installment_metadata": {
            "record_count": sum(
                isinstance(record.get("creditCardMetadata"), dict)
                for record in transaction_records
            ),
            "field_names": nested_keys(transaction_records, "creditCardMetadata"),
            "installment_number_present_count": nested_presence_count(
                transaction_records,
                "creditCardMetadata",
                "installmentNumber",
            ),
            "total_installments_present_count": nested_presence_count(
                transaction_records,
                "creditCardMetadata",
                "totalInstallments",
            ),
            "bill_link_present_count": nested_presence_count(
                transaction_records, "creditCardMetadata", "billId"
            ),
            "bill_forecast_present_count": nested_presence_count(
                transaction_records,
                "creditCardMetadata",
                "billForecastDate",
            ),
        },
        "temporal": {
            "date_present_count": presence_count(transaction_records, "date"),
            "date_span_bucket": temporal_span_bucket(transaction_records, "date"),
            "created_at_present_count": presence_count(
                transaction_records, "createdAt"
            ),
            "created_at_span_bucket": temporal_span_bucket(
                transaction_records, "createdAt"
            ),
        },
        "deduplication": {
            "external_id_present_count": presence_count(transaction_records, "id"),
            "provider_id_present_count": presence_count(
                transaction_records, "providerId"
            ),
            "updated_at_present_count": presence_count(
                transaction_records, "updatedAt"
            ),
            "candidate_fields": [
                "id",
                "accountId",
                "providerId",
                "status",
                "date",
                "createdAt",
                "updatedAt",
                "creditCardMetadata.billId",
                "creditCardMetadata.billForecastDate",
            ],
            "external_id_stability": "MAY_CHANGE_AFTER_MATERIAL_UPDATE",
        },
    }


def bills_summary(payload: JsonValue) -> dict[str, Any]:
    """Summarize credit-card bill structure without retaining bill values."""

    bill_records = records(payload)
    return {
        "queried": True,
        **metadata_inventory(payload),
        "status_counts": safe_enum_counts(bill_records, "status"),
        "allows_installments_present_count": presence_count(
            bill_records, "allowsInstallments"
        ),
        "due_date_present_count": presence_count(bill_records, "dueDate"),
        "closing_date_present_count": presence_count(bill_records, "billClosingDate"),
        "due_date_span_bucket": temporal_span_bucket(bill_records, "dueDate"),
    }


def financial_collection_report(
    *,
    item: JsonValue,
    accounts: JsonValue,
    account_collections: Sequence[FinancialAccountCollection],
    accounts_truncated: bool,
) -> dict[str, Any]:
    """Create the issue #57 report with no external identifier or raw value."""

    credit_cards = sum(
        collection.account_type == "CREDIT"
        and collection.account_subtype == "CREDIT_CARD"
        for collection in account_collections
    )
    account_reports: list[dict[str, Any]] = []
    for collection in account_collections:
        transaction_query_status = (
            "NOT_AVAILABLE_HTTP_404"
            if collection.query_status
            in {
                "TRANSACTIONS_NOT_AVAILABLE_HTTP_404",
                "TRANSACTIONS_AND_BILLS_NOT_AVAILABLE_HTTP_404",
            }
            else "NOT_QUERIED"
            if collection.query_status.startswith("SKIPPED")
            else "SUCCESS"
        )
        transaction_report = transaction_pages_summary(
            collection.transaction_pages,
            truncated=collection.transactions_truncated,
            cursor_pagination_observed=collection.cursor_pagination_observed,
        )
        transaction_report["query_status"] = transaction_query_status

        if collection.bills is not None:
            bills = {"query_status": "SUCCESS", **bills_summary(collection.bills)}
        elif collection.query_status in {
            "BILLS_NOT_AVAILABLE_HTTP_404",
            "TRANSACTIONS_AND_BILLS_NOT_AVAILABLE_HTTP_404",
        }:
            bills = {
                "queried": True,
                "query_status": "NOT_AVAILABLE_HTTP_404",
                "reason": "HTTP_404",
            }
        else:
            bills = {
                "queried": False,
                "query_status": "NOT_APPLICABLE_OR_ACCOUNT_UNAVAILABLE",
                "reason": "NOT_CREDIT_CARD_OR_ACCOUNT_UNAVAILABLE",
            }

        account_reports.append(
            {
                "ordinal": collection.ordinal,
                "type": collection.account_type,
                "subtype": collection.account_subtype,
                "query_status": collection.query_status,
                "transactions": transaction_report,
                "bills": bills,
            }
        )
    return {
        "format": "meufinanceiro-pluggy-spike",
        "version": 2,
        "created_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "mode": "sandbox-financial-collection",
        "item": {
            "status": safe_enum(item.get("status")) if isinstance(item, dict) else None,
            "execution_status": safe_enum(item.get("executionStatus"))
            if isinstance(item, dict)
            else None,
            "metadata": metadata_inventory(item),
        },
        "accounts": {
            "inventory": metadata_inventory(accounts),
            "queried_count": len(account_collections),
            "truncated": accounts_truncated,
            "credit_card_count": credit_cards,
            "credit_card_representation": ("ACCOUNT_TYPE_CREDIT_SUBTYPE_CREDIT_CARD"),
            "records": account_reports,
        },
        "privacy": {
            "raw_responses": False,
            "tokens_persisted": False,
            "financial_values_persisted": False,
            "external_ids_persisted": False,
            "full_provider_dates_persisted": False,
        },
    }


def raw_forbidden_values(payload: JsonValue) -> set[str]:
    """Collect raw values that must never survive report rendering."""

    values: set[str] = set()

    def walk(value: Any, key: str | None = None) -> None:
        if isinstance(value, dict):
            for nested_key, nested in value.items():
                walk(nested, str(nested_key))
            return
        if isinstance(value, list):
            for nested in value:
                walk(nested, key)
            return
        if isinstance(value, str):
            is_uuid = False
            try:
                uuid.UUID(value)
                is_uuid = True
            except ValueError:
                pass
            sensitive_key = bool(key and RAW_SENSITIVE_VALUE_KEY_PATTERN.search(key))
            is_date = bool(ISO_DATETIME_PATTERN.match(value))
            if len(value) >= 4 and (is_uuid or sensitive_key or is_date):
                values.add(value)
            return
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and key
            and re.search(r"(?i)(amount|balance)", key)
        ):
            rendered = str(value)
            if len(rendered) >= 4:
                values.add(rendered)

    walk(payload)
    return values


def report_scalar_values(value: Any) -> set[str]:
    """Return exact rendered scalar values for leak comparison."""

    values: set[str] = set()

    def walk(current: Any) -> None:
        if isinstance(current, dict):
            for nested in current.values():
                walk(nested)
            return
        if isinstance(current, list):
            for nested in current:
                walk(nested)
            return
        if isinstance(current, bool) or current is None:
            return
        if isinstance(current, (str, int, float)):
            values.add(str(current).casefold())

    walk(value)
    return values


def validate_financial_report(
    report: Mapping[str, Any],
    *,
    forbidden_substrings: Sequence[str] = (),
    forbidden_raw_scalars: Sequence[str] = (),
) -> str:
    """Validate credentials by substring and raw payload values exactly."""

    rendered = validate_report(report, forbidden_values=forbidden_substrings)
    scalar_values = report_scalar_values(report)
    for value in forbidden_raw_scalars:
        if value and value.casefold() in scalar_values:
            raise SpikeError("Valor sensível detectado no relatório.")
    return rendered


def validate_collection_limit(value: int, name: str, maximum: int) -> None:
    if value < 1 or value > maximum:
        raise SpikeError(f"{name} deve estar entre 1 e {maximum}.")


def validated_uuid(raw: str, name: str) -> str:
    try:
        return str(uuid.UUID(raw.strip()))
    except ValueError:
        raise SpikeError(f"{name} deve ser um UUID válido.") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Coleta sanitizada de transações, cartões e faturas Pluggy.")
    )
    parser.add_argument("--api-base", help=argparse.SUPPRESS)
    parser.add_argument("--item-id", required=True)
    parser.add_argument("--max-accounts", type=int, default=10)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        validate_collection_limit(
            args.max_accounts, "--max-accounts", MAX_FINANCIAL_ACCOUNTS
        )
        validate_collection_limit(args.max_pages, "--max-pages", MAX_TRANSACTION_PAGES)
        item_id = validated_uuid(args.item_id, "--item-id")
        credentials = credentials_from_environment()
        api_base = resolve_api_base(args.api_base, os.environ)
        client = FinancialPluggyClient(credentials, api_base=api_base)
        api_key = client.authenticate()

        item = client.get_item(api_key, item_id)
        accounts = client.get_product(api_key, "accounts", item_id)
        account_records = records(accounts)
        selected_accounts = account_records[: args.max_accounts]
        collections: list[FinancialAccountCollection] = []
        raw_payloads: list[JsonValue] = [item, accounts]

        for ordinal, account in enumerate(selected_accounts, start=1):
            raw_account_id = account.get("id")
            account_type = safe_enum(account.get("type"))
            account_subtype = safe_enum(account.get("subtype"))
            if not isinstance(raw_account_id, str):
                collections.append(
                    FinancialAccountCollection(
                        ordinal=ordinal,
                        account_type=account_type,
                        account_subtype=account_subtype,
                        query_status="SKIPPED_MISSING_ID",
                        transaction_pages=(),
                        transactions_truncated=False,
                        cursor_pagination_observed=False,
                        bills=None,
                    )
                )
                continue
            try:
                account_id = str(uuid.UUID(raw_account_id))
            except ValueError:
                collections.append(
                    FinancialAccountCollection(
                        ordinal=ordinal,
                        account_type=account_type,
                        account_subtype=account_subtype,
                        query_status="SKIPPED_INVALID_ID",
                        transaction_pages=(),
                        transactions_truncated=False,
                        cursor_pagination_observed=False,
                        bills=None,
                    )
                )
                continue

            collection = collect_account_financial_data(
                client,
                api_key,
                account_id,
                ordinal=ordinal,
                account_type=account_type,
                account_subtype=account_subtype,
                max_pages=args.max_pages,
            )
            raw_payloads.extend(collection.transaction_pages)
            if collection.bills is not None:
                raw_payloads.append(collection.bills)
            collections.append(collection)

        report = financial_collection_report(
            item=item,
            accounts=accounts,
            account_collections=collections,
            accounts_truncated=len(account_records) > len(selected_accounts),
        )
        forbidden_substrings = {
            credentials.client_id,
            credentials.client_secret,
            api_key,
            item_id,
        }
        forbidden_raw_scalars: set[str] = set()
        for payload in raw_payloads:
            forbidden_raw_scalars.update(raw_forbidden_values(payload))
        validate_financial_report(
            report,
            forbidden_substrings=tuple(sorted(forbidden_substrings)),
            forbidden_raw_scalars=tuple(sorted(forbidden_raw_scalars)),
        )
        output = local_output_path(
            args.output or default_report_path("financial-collection")
        )
        write_report(
            report,
            output,
            forbidden_values=tuple(sorted(forbidden_substrings)),
        )
        print(f"Prova sanitizada gravada em {output}")
        return 0
    except SpikeError as exc:
        print(f"ERRO: {html.escape(str(exc))}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
