import json
import logging
import signal
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    worker_health_port: int = 8081
    app_log_level: str = "INFO"

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")


settings = Settings()  # type: ignore[call-arg]
logging.basicConfig(
    level=getattr(logging, settings.app_log_level.upper(), logging.INFO),
    format='{"timestamp":"%(asctime)s","level":"%(levelname)s","service":"worker","message":"%(message)s"}',
)
logger = logging.getLogger("meufinanceiro.worker")
stop_event = threading.Event()


def database_is_ready() -> bool:
    try:
        with psycopg.connect(settings.database_url, connect_timeout=2) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        return True
    except psycopg.Error:
        return False


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib contract
        if self.path != "/health":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        database_ok = database_is_ready()
        status = HTTPStatus.OK if database_ok else HTTPStatus.SERVICE_UNAVAILABLE
        payload = json.dumps(
            {
                "status": "ok" if database_ok else "degraded",
                "service": "worker",
                "database": "ok" if database_ok else "unavailable",
            }
        ).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


def request_shutdown(signum: int, _frame: object) -> None:
    logger.info("shutdown requested signal=%s", signum)
    stop_event.set()


def main() -> None:
    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)

    server = ThreadingHTTPServer(
        ("0.0.0.0", settings.worker_health_port), HealthHandler
    )
    server.timeout = 1
    logger.info("worker started health_port=%s", settings.worker_health_port)

    while not stop_event.is_set():
        server.handle_request()

    server.server_close()
    logger.info("worker stopped")


if __name__ == "__main__":
    main()
