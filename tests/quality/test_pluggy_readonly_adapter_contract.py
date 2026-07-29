from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPOSITORY_ROOT / "packages/banking-pluggy"
SOURCE_ROOT = PACKAGE_ROOT / "src/meufinanceiro_banking_pluggy"
SOURCE_TEXT = "\n".join(
    path.read_text(encoding="utf-8")
    for path in sorted(SOURCE_ROOT.glob("*.py"))
)
PYPROJECT_TEXT = (PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
API_MAIN_TEXT = (REPOSITORY_ROOT / "apps/api/app/main.py").read_text(encoding="utf-8")
API_DOCKERFILE_TEXT = (REPOSITORY_ROOT / "apps/api/Dockerfile").read_text(
    encoding="utf-8"
)
API_PYPROJECT_TEXT = (REPOSITORY_ROOT / "apps/api/pyproject.toml").read_text(
    encoding="utf-8"
)
QUALITY_WORKFLOW_TEXT = (
    REPOSITORY_ROOT / ".github/workflows/quality.yml"
).read_text(encoding="utf-8")
LOCAL_QUALITY_TEXT = (
    REPOSITORY_ROOT / "infra/scripts/run-quality.py"
).read_text(encoding="utf-8")


def test_adapter_source_has_no_transport_or_secret_surface() -> None:
    lowered = SOURCE_TEXT.casefold()

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


def test_adapter_package_has_only_neutral_internal_dependency() -> None:
    assert '"meufinanceiro-banking==0.1.0"' in PYPROJECT_TEXT
    assert "httpx" not in PYPROJECT_TEXT.casefold()
    assert "requests" not in PYPROJECT_TEXT.casefold()


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
