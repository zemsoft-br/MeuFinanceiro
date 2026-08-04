from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPOSITORY_ROOT / "packages/banking-pluggy"
SOURCE_ROOT = PACKAGE_ROOT / "src/meufinanceiro_banking_pluggy"
BOUNDARY_SOURCE_TEXT = "\n".join(
    (SOURCE_ROOT / name).read_text(encoding="utf-8")
    for name in ("__init__.py", "adapter.py", "gateway.py")
)
TRANSPORT_SOURCE_TEXT = (SOURCE_ROOT / "transport.py").read_text(encoding="utf-8")
TRANSPORT_TEST_TEXT = (PACKAGE_ROOT / "tests/test_transport.py").read_text(
    encoding="utf-8"
)
PYPROJECT_TEXT = (PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
API_MAIN_TEXT = (REPOSITORY_ROOT / "apps/api/app/main.py").read_text(encoding="utf-8")
API_DOCKERFILE_TEXT = (REPOSITORY_ROOT / "apps/api/Dockerfile").read_text(
    encoding="utf-8"
)
API_PYPROJECT_TEXT = (REPOSITORY_ROOT / "apps/api/pyproject.toml").read_text(
    encoding="utf-8"
)
QUALITY_WORKFLOW_TEXT = (REPOSITORY_ROOT / ".github/workflows/quality.yml").read_text(
    encoding="utf-8"
)
LOCAL_QUALITY_TEXT = (REPOSITORY_ROOT / "infra/scripts/run-quality.py").read_text(
    encoding="utf-8"
)


def test_adapter_boundary_has_no_transport_or_secret_surface() -> None:
    lowered = BOUNDARY_SOURCE_TEXT.casefold()

    for forbidden in (
        "httpx",
        "requests",
        "urllib",
        "urlopen",
        "fastapi",
        "sqlalchemy",
        "meufinanceiro_persistence",
        "os.environ",
        "client_secret",
        "connect_token",
        "api_key",
        "password",
        "private_key",
    ):
        assert forbidden not in lowered

    assert "PluggyHttpTransport" not in BOUNDARY_SOURCE_TEXT
    assert "PluggyApplicationCredentials" not in BOUNDARY_SOURCE_TEXT


def test_transport_is_internal_bounded_and_does_not_read_configuration() -> None:
    lowered = TRANSPORT_SOURCE_TEXT.casefold()

    assert "import httpx" in TRANSPORT_SOURCE_TEXT
    assert '"https://api.pluggy.ai"' in TRANSPORT_SOURCE_TEXT
    assert "_MAX_ATTEMPTS: Final = 3" in TRANSPORT_SOURCE_TEXT
    assert "follow_redirects=False" in TRANSPORT_SOURCE_TEXT
    assert "trust_env=False" in TRANSPORT_SOURCE_TEXT
    assert "X-API-KEY" in TRANSPORT_SOURCE_TEXT
    assert "RateLimit-Reset" in TRANSPORT_SOURCE_TEXT
    assert "Retry-After" in TRANSPORT_SOURCE_TEXT
    assert "apiKey" in TRANSPORT_SOURCE_TEXT
    assert "accessToken" in TRANSPORT_SOURCE_TEXT

    for forbidden in (
        "os.environ",
        "load_dotenv",
        "dotenv",
        "argparse",
        "response.text",
        "response.json()",
        "raise_for_status",
        "print(",
    ):
        assert forbidden not in lowered


def test_transport_package_pins_only_reviewed_dependencies() -> None:
    assert '"meufinanceiro-banking==0.1.0"' in PYPROJECT_TEXT
    assert '"httpx==0.28.1"' in PYPROJECT_TEXT
    assert "requests" not in PYPROJECT_TEXT.casefold()


def test_transport_tests_use_only_mocked_loopback_http() -> None:
    assert "httpx.MockTransport" in TRANSPORT_TEST_TEXT
    assert "http://127.0.0.1" in TRANSPORT_TEST_TEXT
    assert "http://localhost" in TRANSPORT_TEST_TEXT
    assert "https://api.pluggy.ai" not in TRANSPORT_TEST_TEXT
    assert "socket" not in TRANSPORT_TEST_TEXT


def test_api_runtime_does_not_install_or_register_adapter() -> None:
    package_name = "meufinanceiro-banking-pluggy"
    module_name = "meufinanceiro_banking_pluggy"

    assert package_name not in API_PYPROJECT_TEXT
    assert "packages/banking-pluggy" not in API_DOCKERFILE_TEXT
    assert module_name not in API_MAIN_TEXT
    assert 'register("pluggy"' not in API_MAIN_TEXT


def test_quality_gates_include_adapter_package() -> None:
    for content in (QUALITY_WORKFLOW_TEXT, LOCAL_QUALITY_TEXT):
        assert "packages/banking-pluggy" in content
