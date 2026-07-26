#!/usr/bin/env python3
"""Disposable Pluggy Sandbox laboratory for issue #53.

This tool is intentionally isolated from the MeuFinanceiro runtime. It uses only
the Python standard library, reads credentials from environment variables, and
never writes raw API responses or authentication tokens to disk.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import secrets
import stat
import sys
import threading
import time
import uuid
import webbrowser
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE = "https://api.pluggy.ai"
LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_OUTPUT_DIRECTORY = Path(".pluggy-spike")
MAX_CALLBACK_BYTES = 16_384
MAX_REQUEST_ATTEMPTS = 3
RETRY_BASE_SECONDS = 0.25
ALLOWED_CALLBACK_OUTCOMES = {"success", "error", "widget-load-error"}
ALLOWED_PRODUCTS = {
    "accounts": "/accounts",
    "investments": "/investments",
    "loans": "/loans",
}
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


class SpikeError(RuntimeError):
    """Safe error intended for operator-facing output."""


@dataclass(frozen=True)
class Credentials:
    client_id: str
    client_secret: str


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _urlopen_transport(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        return bytes(response.read())


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


class PluggyClient:
    def __init__(
        self,
        credentials: Credentials,
        *,
        api_base: str = API_BASE,
        timeout: float = 15.0,
        transport: Transport = _urlopen_transport,
        sleeper: Sleeper = time.sleep,
    ) -> None:
        self._credentials = credentials
        self._api_base = api_base.rstrip("/")
        self._timeout = timeout
        self._transport = transport
        self._sleeper = sleeper

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        api_key: str | None = None,
    ) -> JsonValue:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "MeuFinanceiro-Pluggy-Spike/1",
        }
        if api_key:
            headers["X-API-KEY"] = api_key
        data = None
        if body is not None:
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        request = Request(
            f"{self._api_base}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        raw: bytes | None = None
        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            try:
                raw = self._transport(request, self._timeout)
                break
            except HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code <= 599
                if retryable and attempt < MAX_REQUEST_ATTEMPTS:
                    self._sleeper(RETRY_BASE_SECONDS * attempt)
                    continue
                raise SpikeError(f"Pluggy respondeu HTTP {exc.code}.") from None
            except (URLError, TimeoutError):
                if attempt < MAX_REQUEST_ATTEMPTS:
                    self._sleeper(RETRY_BASE_SECONDS * attempt)
                    continue
                raise SpikeError(
                    "Falha de rede ou timeout ao acessar a Pluggy."
                ) from None
        if raw is None:
            raise SpikeError("A Pluggy não retornou resposta.")

        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SpikeError("A Pluggy retornou JSON inválido.") from None
        if not isinstance(decoded, (dict, list)):
            raise SpikeError("A Pluggy retornou um payload inesperado.")
        return decoded

    def authenticate(self) -> str:
        payload = self._request_json(
            "POST",
            "/auth",
            body={
                "clientId": self._credentials.client_id,
                "clientSecret": self._credentials.client_secret,
            },
        )
        if not isinstance(payload, dict):
            raise SpikeError("Resposta de autenticação inválida.")
        access_token = payload.get("accessToken")
        if not isinstance(access_token, str) or not access_token:
            raise SpikeError("Resposta de autenticação sem accessToken.")
        return access_token

    def list_sandbox_connectors(self, api_key: str) -> JsonValue:
        query = urlencode({"sandbox": "true", "countries": "BR"})
        return self._request_json("GET", f"/connectors?{query}", api_key=api_key)

    def create_connect_token(self, api_key: str, client_user_id: str) -> str:
        payload = self._request_json(
            "POST",
            "/connect_token",
            api_key=api_key,
            body={
                "options": {
                    "clientUserId": client_user_id,
                    "avoidDuplicates": True,
                }
            },
        )
        if not isinstance(payload, dict):
            raise SpikeError("Resposta de Connect Token inválida.")
        access_token = payload.get("accessToken")
        if not isinstance(access_token, str) or not access_token:
            raise SpikeError("Resposta sem Connect Token.")
        return access_token

    def get_item(self, api_key: str, item_id: str) -> JsonValue:
        return self._request_json("GET", f"/items/{item_id}", api_key=api_key)

    def get_product(self, api_key: str, product: str, item_id: str) -> JsonValue:
        endpoint = ALLOWED_PRODUCTS.get(product)
        if endpoint is None:
            raise SpikeError(f"Produto não permitido: {product}")
        query = urlencode({"itemId": item_id})
        return self._request_json("GET", f"{endpoint}?{query}", api_key=api_key)


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
    field_names = sorted({key for record in records for key in record})
    container_keys = sorted(payload) if isinstance(payload, dict) else []
    return {
        "record_count": len(records),
        "field_names": field_names,
        "container_keys": container_keys,
    }


def _status_value(payload: JsonValue, key: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    return value if isinstance(value, str) else None


def fingerprint(value: str, salt: bytes) -> str:
    digest = hashlib.sha256(salt + value.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def probe_report(connectors: JsonValue) -> dict[str, Any]:
    inventory = metadata_inventory(connectors)
    return {
        "format": "meufinanceiro-pluggy-spike",
        "version": 1,
        "created_at_utc": utc_now(),
        "mode": "sandbox-probe",
        "authentication": "ok",
        "connectors": inventory,
        "privacy": {
            "raw_responses": False,
            "tokens_persisted": False,
            "financial_values_persisted": False,
        },
    }


def collection_report(
    *,
    item_id: str,
    item: JsonValue,
    products: Mapping[str, JsonValue],
    salt: bytes | None = None,
) -> dict[str, Any]:
    run_salt = salt if salt is not None else secrets.token_bytes(32)
    return {
        "format": "meufinanceiro-pluggy-spike",
        "version": 1,
        "created_at_utc": utc_now(),
        "mode": "sandbox-collection",
        "item": {
            "fingerprint": fingerprint(item_id, run_salt),
            "status": _status_value(item, "status"),
            "execution_status": _status_value(item, "executionStatus"),
            "metadata": metadata_inventory(item),
        },
        "products": {
            product: metadata_inventory(payload)
            for product, payload in sorted(products.items())
        },
        "privacy": {
            "raw_responses": False,
            "tokens_persisted": False,
            "financial_values_persisted": False,
            "salt_exported": False,
        },
    }


def validate_report(
    report: Mapping[str, Any],
    *,
    forbidden_values: Sequence[str] = (),
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


def default_report_path(prefix: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_OUTPUT_DIRECTORY / "reports" / f"{prefix}-{timestamp}.json"


def local_output_path(path: Path) -> Path:
    root = (Path.cwd() / DEFAULT_OUTPUT_DIRECTORY).resolve()
    candidate = (Path.cwd() / path).resolve()
    if candidate != root and root not in candidate.parents:
        raise SpikeError("A saída deve permanecer dentro de .pluggy-spike/.")
    return candidate


def _widget_html(connect_token: str) -> bytes:
    token_json = json.dumps(connect_token)
    page = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="Content-Security-Policy"
        content="default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.pluggy.ai;
        connect-src 'self' https://*.pluggy.ai; frame-src https://*.pluggy.ai;
        style-src 'self' 'unsafe-inline'; img-src 'self' data: https://*.pluggy.ai">
  <title>MeuFinanceiro - Pluggy Sandbox</title>
  <script src="https://cdn.pluggy.ai/pluggy-connect/v2.7.0/pluggy-connect.js"></script>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 760px; margin: 3rem auto; padding: 0 1rem; }}
    button {{ padding: .75rem 1rem; font-size: 1rem; }}
    code {{ background: #eee; padding: .15rem .3rem; }}
    #status {{ margin-top: 1rem; white-space: pre-wrap; }}
  </style>
</head>
<body>
  <h1>Laboratório Pluggy Sandbox</h1>
  <p>Use somente o conector <strong>Pluggy Bank</strong> e dados de teste.</p>
  <p>Credenciais de sucesso do sandbox: <code>user-ok</code> /
     <code>password-ok</code>; MFA: <code>123456</code>.</p>
  <button id="open" type="button">Abrir Pluggy Connect Sandbox</button>
  <div id="status">Nenhuma conexão iniciada.</div>
  <script>
    const statusNode = document.getElementById('status');
    async function record(outcome, payload) {{
      const item = payload && (payload.item || payload);
      const body = {{
        outcome,
        itemId: item && typeof item.id === 'string' ? item.id : null,
        executionStatus: item && typeof item.executionStatus === 'string'
          ? item.executionStatus : null
      }};
      await fetch('/callback', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify(body)
      }});
      statusNode.textContent = 'Callback sanitizado registrado: ' + outcome;
    }}
    const widget = new PluggyConnect({{
      connectToken: {token_json},
      includeSandbox: true,
      language: 'pt',
      onSuccess: (data) => record('success', data),
      onError: (error) => record('error', error && error.data ? error.data : null)
    }});
    document.getElementById('open').addEventListener('click', async () => {{
      statusNode.textContent = 'Abrindo widget...';
      try {{
        await widget.init();
      }} catch (_) {{
        statusNode.textContent = 'Falha ao abrir o widget. Consulte o terminal.';
        await record('widget-load-error', null);
      }}
    }});
  </script>
</body>
</html>"""
    return page.encode("utf-8")


def sanitized_callback(payload: Mapping[str, Any]) -> dict[str, str | None]:
    raw_item_id = payload.get("itemId")
    item_id: str | None = None
    if isinstance(raw_item_id, str):
        try:
            item_id = str(uuid.UUID(raw_item_id))
        except ValueError:
            item_id = None

    raw_status = payload.get("executionStatus")
    execution_status = (
        raw_status
        if isinstance(raw_status, str)
        and 1 <= len(raw_status) <= 64
        and raw_status.replace("_", "").isalnum()
        else None
    )

    raw_outcome = payload.get("outcome")
    outcome = (
        raw_outcome
        if isinstance(raw_outcome, str) and raw_outcome in ALLOWED_CALLBACK_OUTCOMES
        else "unknown"
    )
    return {
        "recorded_at_utc": utc_now(),
        "outcome": outcome,
        "item_id": item_id,
        "execution_status": execution_status,
    }


class CallbackStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def save(self, payload: Mapping[str, Any]) -> None:
        safe_payload = sanitized_callback(payload)
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(safe_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )


def make_handler(
    connect_token: str, store: CallbackStore
) -> type[BaseHTTPRequestHandler]:
    page = _widget_html(connect_token)

    class Handler(BaseHTTPRequestHandler):
        server_version = "MeuFinanceiroPluggySpike/1"

        def log_message(self, format_string: str, *args: object) -> None:
            del format_string, args

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/":
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
                return
            if self.path == "/health":
                body = b'{"status":"ok","mode":"sandbox"}\n'
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/callback":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > MAX_CALLBACK_BYTES:
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            try:
                payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            if not isinstance(payload, dict):
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            store.save(payload)
            body = b'{"stored":true}\n'
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def serve_widget(
    connect_token: str,
    *,
    port: int,
    open_browser: bool,
    session_path: Path,
) -> None:
    store = CallbackStore(session_path)
    server = ThreadingHTTPServer(
        (LOOPBACK_HOST, port),
        make_handler(connect_token, store),
    )
    url = f"http://{LOOPBACK_HOST}:{server.server_port}/"
    print(f"Laboratório sandbox em {url}")
    print("Use somente Pluggy Bank. Pressione Ctrl+C para encerrar.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Encerrando laboratório.")
    finally:
        server.server_close()


def resolve_api_base(requested: str | None, environment: Mapping[str, str]) -> str:
    if not requested:
        return API_BASE
    if environment.get("PLUGGY_SPIKE_ALLOW_TEST_API_BASE") != "1":
        raise SpikeError(
            "--api-base é permitido somente em testes com "
            "PLUGGY_SPIKE_ALLOW_TEST_API_BASE=1."
        )
    return requested


def parse_products(raw: str) -> list[str]:
    products = [entry.strip() for entry in raw.split(",") if entry.strip()]
    invalid = sorted(set(products) - set(ALLOWED_PRODUCTS))
    if invalid:
        raise SpikeError("Produtos não permitidos: " + ", ".join(invalid))
    return products


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Laboratório descartável Pluggy Sandbox do MeuFinanceiro."
    )
    parser.add_argument("--api-base", help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("probe", help="Valida auth e conectores sandbox.")
    probe.add_argument("--output", type=Path)

    serve = subparsers.add_parser("serve", help="Abre o Connect Widget sandbox local.")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--no-browser", action="store_true")
    serve.add_argument("--client-user-id")
    serve.add_argument(
        "--session-output",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY / "last-item.json",
    )

    collect = subparsers.add_parser(
        "collect", help="Coleta somente metadados sanitizados de um Item sandbox."
    )
    collect.add_argument("--item-id", required=True)
    collect.add_argument(
        "--products",
        default="accounts",
        help="Lista separada por vírgulas: accounts, investments, loans.",
    )
    collect.add_argument("--output", type=Path)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        credentials = credentials_from_environment()
        api_base = resolve_api_base(args.api_base, os.environ)
        client = PluggyClient(credentials, api_base=api_base)
        api_key = client.authenticate()

        if args.command == "probe":
            report = probe_report(client.list_sandbox_connectors(api_key))
            output = local_output_path(args.output or default_report_path("probe"))
            write_report(
                report,
                output,
                forbidden_values=(
                    credentials.client_id,
                    credentials.client_secret,
                    api_key,
                ),
            )
            print(f"Prova sanitizada gravada em {output}")
            return 0

        if args.command == "serve":
            client_user_id = args.client_user_id or f"sandbox-{secrets.token_hex(8)}"
            connect_token = client.create_connect_token(api_key, client_user_id)
            serve_widget(
                connect_token,
                port=args.port,
                open_browser=not args.no_browser,
                session_path=local_output_path(args.session_output),
            )
            return 0

        if args.command == "collect":
            products = parse_products(args.products)
            item = client.get_item(api_key, args.item_id)
            product_payloads = {
                product: client.get_product(api_key, product, args.item_id)
                for product in products
            }
            report = collection_report(
                item_id=args.item_id,
                item=item,
                products=product_payloads,
            )
            output = local_output_path(args.output or default_report_path("collection"))
            write_report(
                report,
                output,
                forbidden_values=(
                    credentials.client_id,
                    credentials.client_secret,
                    api_key,
                    args.item_id,
                ),
            )
            print(f"Prova sanitizada gravada em {output}")
            return 0

        raise SpikeError("Comando desconhecido.")
    except SpikeError as exc:
        print(f"ERRO: {html.escape(str(exc))}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
