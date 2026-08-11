from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "packages" / "finance" / "pyproject.toml"
MONEY = (
    ROOT
    / "packages"
    / "finance"
    / "src"
    / "meufinanceiro_finance"
    / "money.py"
)
ADR = ROOT / "docs" / "adr" / "0015-canonical-money-representation-and-rounding.md"
QUALITY = ROOT / "infra" / "scripts" / "run-quality.py"
WORKFLOW = ROOT / ".github" / "workflows" / "quality.yml"
LICENSES = ROOT / "infra" / "scripts" / "check-python-licenses.py"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_finance_package_has_no_runtime_dependencies() -> None:
    pyproject = PYPROJECT.read_text(encoding="utf-8")

    assert 'dependencies = []' in pyproject
    assert "fastapi" not in pyproject.lower()
    assert "sqlalchemy" not in pyproject.lower()
    assert "httpx" not in pyproject.lower()
    assert "pluggy" not in pyproject.lower()


def test_money_module_uses_only_standard_library_boundaries() -> None:
    imports = _imports(MONEY)

    assert imports <= {"__future__", "dataclasses", "decimal", "enum", "functools"}


def test_money_adr_is_accepted_and_explicit() -> None:
    adr = ADR.read_text(encoding="utf-8")

    assert "- Status: Accepted" in adr
    assert "NUMERIC(24,8)" in adr
    assert "string decimal fixed-point" in adr
    assert "Não existe modo default" in adr
    assert "`float` não é aceito" in adr


def test_quality_contract_includes_finance_package() -> None:
    local_quality = QUALITY.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    licenses = LICENSES.read_text(encoding="utf-8")

    for content in (local_quality, workflow):
        assert "packages/finance" in content
        assert "packages/finance/tests" in content
        assert "packages/finance/src" in content

    assert '"meufinanceiro-finance"' in licenses
