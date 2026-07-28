#!/usr/bin/env python3
"""Read-only Pluggy authentication lifecycle laboratory for issue #59."""

from __future__ import annotations

import argparse
import html
import json
import os
import random
import re
import stat
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE = "https://api.pluggy.ai"
DEFAULT_OUTPUT_DIRECTORY = Path(".pluggy-spike")
API_KEY_EXPIRATION_SECONDS = 2 * 60 * 60
EXPIRATION_OBSERVATION_MARGIN_SECONDS = 60
MAX_REQUEST_ATTEMPTS = 3
RETRY_BASE_SECONDS = 0.5
RETRY_MAX_SECONDS = 4.0
MAX_RATE_LIMIT_WAIT_SECONDS = 60.0
SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)(access[_-]?token|connect[_-]?token|client[_-]?secret|"
    r"password|credential|private[_-]?key|account[_-]?number|document|cpf|cnpj)"
)
JWT_PATTERN = re.compile(
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
)

JsonValue = dict[str, Any] | list[Any]
Transport = Callable[[Request, float], bytes]
Sleeper = Callable[[float], None]
Jitter = Callable[[float], float]


class SpikeError(RuntimeError):
    """Safe error intended for operator-facing output."""


class AuthenticationRejected(RuntimeError):
    """Internal signal for an authenticated request rejected with 401/403."""

    def __init__(self, status_code: int) -> None:
        super().__init__(status_code)
        self.status_code = status_code


@dataclass(frozen=True)
class Credentials:
    client_id: str
    client_secret: str


@dataclass(frozen=True)
class RateLimitDecision:
    wait_seconds: float | None
    retry_after_present: bool
    rate_limit_reset_present: bool


@dataclass
class RequestTrace:
    attempts: int = 0
    authentication_requests: int = 0
    resource_requests: int = 0
    auth_refreshes: int = 0
    transient_failures: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    wait_buckets: dict[str, int] = field(default_factory=dict)
    retry_after_observed: bool = False
    rate_limit_reset_observed: bool = False

    def record_attempt(self, request_kind: str) -> None:
        self.attempts += 1
        if request_kind == "AUTHENTICATION":
            self.authentication_requests += 1
        else:
            self.resource_requests += 1

    def record_status(self, status_code: int) -> None:
        key = str(status_code)
        self.status_counts[key] = self.status_counts.get(key, 0) + 1

    def record_wait(self, seconds: float) -> None:
        bucket = wait_bucket(seconds)
        self.wait_buckets[bucket] = self.wait_buckets.get(bucket, 0) + 1


def _urlopen_transport(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        return bytes(response.read())


def _default_jitter(delay: float) -> float:
    return random.uniform(0.0, min(delay * 0.25, 1.0))  # noqa: S311


def credentials_from_environment(
    environment: Mapping[str, str] | None = None,
) -> Credentials:
    source = environment if environment is not None else os.environ
    client_id = source.get("PLUGGY_CLIENT_ID", "").strip()
    client_secret = source.get("PLUGGY_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise SpikeError(
            "Defina PLUGGY_CLIENT_ID e PLUGGY_CLIENT_SECRET somente no ambiente local."
        )
    return Credentials(client_id=client_id, client_secret=client_secret)


def resolve_api_base(requested: str | None, environment: Mapping[str, str]) -> str:
    if not requested:
        return API_BASE
    if environment.get("PLUGGY_SPIKE_ALLOW_TEST_API_BASE") != "1":
        raise SpikeError(
            "--api-base é permitido somente em testes com "
            "PLUGGY_SPIKE_ALLOW_TEST_API_BASE=1."
        )
    return requested


def _header_mapping(error: HTTPError) -> Mapping[str, str] | None:
    if error.headers is None:
        return None
    return cast(Mapping[str, str], error.headers)


def _positive_seconds(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw.strip())
    except ValueError:
        return None
    if value <= 0 or value > MAX_RATE_LIMIT_WAIT_SECONDS:
        return None
    return value


def rate_limit_decision(headers: Mapping[str, str] | None) -> RateLimitDecision:
    retry_after = headers.get("Retry-After") if headers is not None else None
    rate_limit_reset = headers.get("RateLimit-Reset") if headers is not None else None
    reset_seconds = _positive_seconds(rate_limit_reset)
    retry_seconds = _positive_seconds(retry_after)
    return RateLimitDecision(
        wait_seconds=reset_seconds if reset_seconds is not None else retry_seconds,
        retry_after_present=retry_after is not None,
        rate_limit_reset_present=rate_limit_reset is not None,
    )


def wait_bucket(seconds: float) -> str:
    if seconds < 1:
        return "UNDER_1_SECOND"
    if seconds <= 5:
        return "ONE_TO_FIVE_SECONDS"
    if seconds <= 30:
        return "SIX_TO_THIRTY_SECONDS"
    return "THIRTY_ONE_TO_SIXTY_SECONDS"


def expiration_wait_bucket(seconds: float) -> str:
    if seconds >= API_KEY_EXPIRATION_SECONDS:
        return "TWO_HOURS_OR_MORE"
    if seconds >= 60 * 60:
        return "ONE_TO_TWO_HOURS"
    return "UNDER_ONE_HOUR"


def _decode_json(raw: bytes) -> JsonValue:
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SpikeError("A Pluggy retornou JSON inválido.") from None
    if not isinstance(decoded, (dict, list)):
        raise SpikeError("A Pluggy retornou um payload inesperado.")
    return decoded


def _backoff_seconds(attempt: int, jitter: Jitter) -> float:
    base = min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * (2 ** (attempt - 1)))
    return min(RETRY_MAX_SECONDS, base + max(0.0, jitter(base)))


class AuthLifecycleClient:
    """Read-only client with bounded retry and one API-key refresh."""

    def __init__(
        self,
        credentials: Credentials,
        *,
        api_base: str = API_BASE,
        timeout: float = 15.0,
        transport: Transport = _urlopen_transport,
        sleeper: Sleeper = time.sleep,
        jitter: Jitter = _default_jitter,
    ) -> None:
        self._credentials = credentials
        self._api_base = api_base.rstrip("/")
        self._timeout = timeout
        self._transport = transport
        self._sleeper = sleeper
        self._jitter = jitter
        self._issued_api_keys: list[str] = []

    @property
    def issued_api_keys(self) -> tuple[str, ...]:
        return tuple(self._issued_api_keys)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        trace: RequestTrace,
        request_kind: str,
        body: Mapping[str, Any] | None = None,
        api_key: str | None = None,
    ) -> JsonValue:
        data = None
        if body is not None:
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")

        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "MeuFinanceiro-Pluggy-Auth-Lifecycle/1",
            }
            if api_key is not None:
                headers["X-API-KEY"] = api_key
            request = Request(
                f"{self._api_base}{path}",
                data=data,
                headers=headers,
                method=method,
            )
            trace.record_attempt(request_kind)
            try:
                return _decode_json(self._transport(request, self._timeout))
            except HTTPError as exc:
                trace.record_status(exc.code)
                if exc.code in {401, 403}:
                    raise AuthenticationRejected(exc.code) from None
                if exc.code == 429:
                    decision = rate_limit_decision(_header_mapping(exc))
                    trace.retry_after_observed |= decision.retry_after_present
                    trace.rate_limit_reset_observed |= decision.rate_limit_reset_present
                    if (
                        attempt < MAX_REQUEST_ATTEMPTS
                        and decision.wait_seconds is not None
                    ):
                        trace.record_wait(decision.wait_seconds)
                        self._sleeper(decision.wait_seconds)
                        continue
                    if decision.wait_seconds is None:
                        raise SpikeError(
                            "Pluggy respondeu HTTP 429 sem janela segura para retry."
                        ) from None
                    raise SpikeError(
                        "Pluggy respondeu HTTP 429 após o limite de tentativas."
                    ) from None
                if 500 <= exc.code <= 599:
                    trace.transient_failures += 1
                    if attempt < MAX_REQUEST_ATTEMPTS:
                        delay = _backoff_seconds(attempt, self._jitter)
                        trace.record_wait(delay)
                        self._sleeper(delay)
                        continue
                raise SpikeError(f"Pluggy respondeu HTTP {exc.code}.") from None
            except (URLError, TimeoutError):
                trace.transient_failures += 1
                if attempt < MAX_REQUEST_ATTEMPTS:
                    delay = _backoff_seconds(attempt, self._jitter)
                    trace.record_wait(delay)
                    self._sleeper(delay)
                    continue
                raise SpikeError(
                    "Falha de rede ou timeout ao acessar a Pluggy."
                ) from None

        raise SpikeError("A Pluggy não retornou resposta.")

    def authenticate(self, trace: RequestTrace) -> str:
        try:
            payload = self._request_json(
                "POST",
                "/auth",
                trace=trace,
                request_kind="AUTHENTICATION",
                body={
                    "clientId": self._credentials.client_id,
                    "clientSecret": self._credentials.client_secret,
                },
            )
        except AuthenticationRejected:
            raise SpikeError("Credenciais da Pluggy foram rejeitadas.") from None
        if not isinstance(payload, dict):
            raise SpikeError("Resposta de autenticação inválida.")
        value = payload.get("apiKey")
        if not isinstance(value, str) or not value:
            value = payload.get("accessToken")
        if not isinstance(value, str) or not value:
            raise SpikeError("Resposta de autenticação sem apiKey.")
        self._issued_api_keys.append(value)
        return value

    def _list_connectors(self, api_key: str, trace: RequestTrace) -> JsonValue:
        query = urlencode({"sandbox": "true", "countries": "BR"})
        return self._request_json(
            "GET",
            f"/connectors?{query}",
            trace=trace,
            request_kind="READ_ONLY_RESOURCE",
            api_key=api_key,
        )

    def list_connectors_with_refresh(
        self, api_key: str, trace: RequestTrace
    ) -> tuple[JsonValue, str]:
        try:
            return self._list_connectors(api_key, trace), api_key
        except AuthenticationRejected:
            trace.auth_refreshes += 1
            refreshed_api_key = self.authenticate(trace)
            try:
                payload = self._list_connectors(refreshed_api_key, trace)
            except AuthenticationRejected:
                raise SpikeError(
                    "API key rejeitada após uma única renovação."
                ) from None
            return payload, refreshed_api_key


def _records(payload: JsonValue) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [entry for entry in payload if isinstance(entry, dict)]
    for key in ("results", "data", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [entry for entry in value if isinstance(entry, dict)]
    return [payload]


def metadata_inventory(payload: JsonValue) -> dict[str, Any]:
    records = _records(payload)
    return {
        "record_count": len(records),
        "field_names": sorted({key for record in records for key in record}),
        "container_keys": sorted(payload) if isinstance(payload, dict) else [],
    }


def lifecycle_report(
    connectors: JsonValue,
    trace: RequestTrace,
    *,
    expiration_probe_requested: bool,
    expiration_observed: bool,
    expiration_wait_seconds: float | None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "format": "meufinanceiro-pluggy-auth-lifecycle",
        "version": 1,
        "created_date_utc": datetime.now(UTC).date().isoformat(),
        "mode": "read-only-auth-lifecycle",
        "authentication": {
            "initial_authentication": "SUCCESS",
            "declared_api_key_lifetime": "TWO_HOURS",
            "expiration_probe_requested": expiration_probe_requested,
            "expiration_observed": expiration_observed,
            "automatic_refresh_count": trace.auth_refreshes,
            "maximum_refreshes_per_request": 1,
        },
        "requests": {
            "attempt_count": trace.attempts,
            "authentication_request_count": trace.authentication_requests,
            "read_only_request_count": trace.resource_requests,
            "transient_failure_count": trace.transient_failures,
            "http_status_counts": dict(sorted(trace.status_counts.items())),
            "wait_buckets": dict(sorted(trace.wait_buckets.items())),
            "retry_after_header_observed": trace.retry_after_observed,
            "rate_limit_reset_header_observed": trace.rate_limit_reset_observed,
        },
        "connectors": metadata_inventory(connectors),
        "privacy": {
            "api_key_persisted": False,
            "application_secrets_persisted": False,
            "authorization_headers_persisted": False,
            "raw_responses_persisted": False,
            "financial_data_persisted": False,
            "item_identifiers_persisted": False,
        },
    }
    if expiration_wait_seconds is not None:
        report["authentication"]["expiration_wait_bucket"] = expiration_wait_bucket(
            expiration_wait_seconds
        )
    return report


def _walk_keys(value: Any) -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            keys.append(str(key))
            keys.extend(_walk_keys(nested))
    elif isinstance(value, list):
        for nested in value:
            keys.extend(_walk_keys(nested))
    return keys


def validate_report(
    report: Mapping[str, Any], *, forbidden_values: Sequence[str] = ()
) -> str:
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)
    lowered = rendered.casefold()
    for value in forbidden_values:
        if value and value.casefold() in lowered:
            raise SpikeError("Valor sensível detectado no relatório.")
    if JWT_PATTERN.search(rendered):
        raise SpikeError("Token com formato JWT detectado no relatório.")
    for key in _walk_keys(report):
        if SENSITIVE_KEY_PATTERN.search(key):
            raise SpikeError(f"Chave sensível detectada no relatório: {key}")
    return rendered


def local_output_path(path: Path) -> Path:
    root = (Path.cwd() / DEFAULT_OUTPUT_DIRECTORY).resolve()
    candidate = (Path.cwd() / path).resolve()
    if candidate != root and root not in candidate.parents:
        raise SpikeError("A saída deve permanecer dentro de .pluggy-spike/.")
    return candidate


def default_report_path() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_OUTPUT_DIRECTORY / "reports" / f"auth-lifecycle-{timestamp}.json"


def write_report(
    report: Mapping[str, Any],
    output: Path,
    *,
    forbidden_values: Sequence[str] = (),
) -> None:
    rendered = validate_report(report, forbidden_values=forbidden_values)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"{rendered}\n", encoding="utf-8")
    try:
        output.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Laboratório read-only do ciclo de autenticação Pluggy."
    )
    parser.add_argument("--api-base", help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)
    lifecycle = subparsers.add_parser(
        "auth-lifecycle",
        help="Valida autenticação, renovação e política de retry sem acessar Items.",
    )
    lifecycle.add_argument(
        "--observe-expiration",
        action="store_true",
        help=(
            "Mantém o processo aberto por mais de duas horas para observar "
            "expiração real."
        ),
    )
    lifecycle.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        credentials = credentials_from_environment()
        client = AuthLifecycleClient(
            credentials,
            api_base=resolve_api_base(args.api_base, os.environ),
        )
        trace = RequestTrace()
        api_key = client.authenticate(trace)
        connectors, active_api_key = client.list_connectors_with_refresh(api_key, trace)
        expiration_wait_seconds: float | None = None
        expiration_observed = False

        if args.command == "auth-lifecycle" and args.observe_expiration:
            expiration_wait_seconds = float(
                API_KEY_EXPIRATION_SECONDS + EXPIRATION_OBSERVATION_MARGIN_SECONDS
            )
            refreshes_before = trace.auth_refreshes
            time.sleep(expiration_wait_seconds)
            connectors, active_api_key = client.list_connectors_with_refresh(
                active_api_key, trace
            )
            expiration_observed = trace.auth_refreshes > refreshes_before

        report = lifecycle_report(
            connectors,
            trace,
            expiration_probe_requested=bool(args.observe_expiration),
            expiration_observed=expiration_observed,
            expiration_wait_seconds=expiration_wait_seconds,
        )
        output = local_output_path(args.output or default_report_path())
        write_report(
            report,
            output,
            forbidden_values=(
                credentials.client_id,
                credentials.client_secret,
                *client.issued_api_keys,
            ),
        )
        print(f"Prova sanitizada gravada em {output}")
        return 0
    except SpikeError as exc:
        print(f"ERRO: {html.escape(str(exc))}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
