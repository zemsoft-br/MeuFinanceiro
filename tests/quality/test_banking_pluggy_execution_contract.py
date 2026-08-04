from __future__ import annotations

import inspect
from pathlib import Path

from meufinanceiro_banking_pluggy_execution import PluggyReadOnlyExecutionService

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "packages/banking-pluggy-execution"
SOURCE_ROOT = PACKAGE_ROOT / "src/meufinanceiro_banking_pluggy_execution"
SOURCE_TEXT = "\n".join(
    path.read_text(encoding="utf-8") for path in sorted(SOURCE_ROOT.glob("*.py"))
)
API_MAIN = (ROOT / "apps/api/app/main.py").read_text(encoding="utf-8")
API_DOCKERFILE = (ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8")
API_PYPROJECT = (ROOT / "apps/api/pyproject.toml").read_text(encoding="utf-8")
QUALITY_WORKFLOW = (ROOT / ".github/workflows/quality.yml").read_text(
    encoding="utf-8"
)
LOCAL_QUALITY = (ROOT / "infra/scripts/run-quality.py").read_text(encoding="utf-8")


def test_public_methods_do_not_accept_item_id() -> None:
    for method_name in (
        "get_connection_state",
        "get_capabilities",
        "list_accounts",
        "list_transactions",
    ):
        signature = inspect.signature(getattr(PluggyReadOnlyExecutionService, method_name))
        assert "item_id" not in signature.parameters
        assert "external_connection_id" not in signature.parameters
        for required in ("installation_id", "residence_id", "connection_id"):
            assert required in signature.parameters


def test_execution_package_has_no_api_or_environment_dependency() -> None:
    lowered = SOURCE_TEXT.casefold()
    for forbidden in (
        "fastapi",
        "sqlalchemy",
        "os.environ",
        "dotenv",
        "argparse",
        "logging.",
        "print(",
    ):
        assert forbidden not in lowered


def test_api_runtime_does_not_install_or_register_execution_package() -> None:
    package_name = "meufinanceiro-banking-pluggy-execution"
    module_name = "meufinanceiro_banking_pluggy_execution"
    assert package_name not in API_PYPROJECT
    assert "packages/banking-pluggy-execution" not in API_DOCKERFILE
    assert module_name not in API_MAIN
    assert 'register("pluggy"' not in API_MAIN


def test_quality_gates_include_execution_package() -> None:
    for content in (QUALITY_WORKFLOW, LOCAL_QUALITY):
        assert "packages/banking-pluggy-execution" in content


def test_package_manifest_has_only_expected_internal_dependencies() -> None:
    manifest = (PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for dependency in (
        '"meufinanceiro-banking==0.1.0"',
        '"meufinanceiro-banking-pluggy==0.1.0"',
        '"meufinanceiro-persistence==0.1.0"',
    ):
        assert dependency in manifest
    assert "fastapi" not in manifest.casefold()
