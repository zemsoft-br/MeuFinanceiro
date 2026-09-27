"""Architecture guard for the intentionally local consent classifier."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = (
    ROOT / "packages/banking-sync/src/meufinanceiro_banking_sync/consent_lifecycle.py"
)
PROVIDER = ROOT / "packages/banking/src/meufinanceiro_banking/provider.py"


def test_classifier_has_only_local_standard_library_and_status_imports() -> None:
    tree = ast.parse(LIFECYCLE.read_text(encoding="utf-8"))
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]

    assert not any(isinstance(node, ast.Import) for node in ast.walk(tree))
    assert {
        (node.module, frozenset(alias.name for alias in node.names)) for node in imports
    } == {
        ("__future__", frozenset({"annotations"})),
        ("collections.abc", frozenset({"Callable"})),
        ("dataclasses", frozenset({"dataclass"})),
        ("datetime", frozenset({"UTC", "datetime", "timedelta"})),
        ("enum", frozenset({"StrEnum"})),
        ("typing", frozenset({"TypeAlias"})),
        ("meufinanceiro_persistence", frozenset({"StoredConnectionStatus"})),
    }

    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert called_names.isdisjoint({"open", "eval", "exec", "__import__"})


def test_classifier_input_and_result_shape_exclude_provider_material() -> None:
    tree = ast.parse(LIFECYCLE.read_text(encoding="utf-8"))
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    evaluator = classes["ConsentLifecycleEvaluator"]
    methods = {
        node.name: node for node in evaluator.body if isinstance(node, ast.FunctionDef)
    }
    assert set(methods) == {"__init__", "classify"}
    assert [arg.arg for arg in methods["classify"].args.kwonlyargs] == [
        "connection_status",
        "consent_expires_at",
    ]
    assert [arg.arg for arg in methods["__init__"].args.kwonlyargs] == [
        "policy",
        "clock",
    ]

    result = classes["ConsentLifecycleResult"]
    assert {
        target.id
        for node in result.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(target := node.target, ast.Name)
    } == {"state", "renewal_required", "connection_terminal"}


def test_provider_contract_has_no_consent_mutation() -> None:
    tree = ast.parse(PROVIDER.read_text(encoding="utf-8"))
    provider = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "BankingProvider"
    )
    methods = {node.name for node in provider.body if isinstance(node, ast.FunctionDef)}

    assert "create_reauthentication_intent" in methods
    assert "disconnect" in methods
    assert not any("renew" in method or "consent" in method for method in methods)
