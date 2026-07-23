from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
GUIDE = ROOT / "docs" / "guides" / "INSTALLATION.md"
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _local_link_targets(document: Path) -> list[Path]:
    content = document.read_text(encoding="utf-8")
    targets: list[Path] = []
    for raw_target in MARKDOWN_LINK.findall(content):
        target = raw_target.split("#", maxsplit=1)[0].strip()
        if not target or "://" in target or target.startswith(("mailto:", "#")):
            continue
        targets.append((document.parent / target).resolve())
    return targets


def test_installation_guide_is_linked_from_readme() -> None:
    content = README.read_text(encoding="utf-8")

    assert "docs/guides/INSTALLATION.md" in content
    assert GUIDE.is_file()


def test_readme_and_installation_guide_have_no_broken_local_links() -> None:
    missing = [
        str(target.relative_to(ROOT))
        for document in (README, GUIDE)
        for target in _local_link_targets(document)
        if not target.exists()
    ]

    assert missing == []


def test_installation_guide_preserves_canonical_operator_contract() -> None:
    content = GUIDE.read_text(encoding="utf-8")

    required_snippets = (
        "./infra/scripts/dev-up.sh",
        "& .\\infra\\scripts\\dev-up.ps1",
        "bash infra/scripts/demo-up.sh up",
        "& .\\infra\\scripts\\demo-up.ps1 -Action up",
        "http://127.0.0.1:8080",
        "http://127.0.0.1:8081",
        "docker compose down",
        "APP_HTTP_PORT",
        '"enabled": false',
        '"enabled": true',
        "Python 3",
        "Docker Compose v2",
        "Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass",
    )

    for snippet in required_snippets:
        assert snippet in content


def test_installation_guide_keeps_destructive_demo_purge_explicit() -> None:
    content = GUIDE.read_text(encoding="utf-8")

    assert "Apagar integralmente o ambiente demo" in content
    assert "remove os containers, o volume" in content
    assert "demo-up.sh purge" in content
    assert "demo-up.ps1 -Action purge" in content
    assert "não deve remover o volume do ambiente comum" in content
