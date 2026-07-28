#!/usr/bin/env python3
"""Report installed Python licenses and reject known incompatible terms."""

from __future__ import annotations

import re
from importlib import metadata

DENIED = re.compile(
    r"GPL-2\.0-only|SSPL|BUSL|Business Source License|Commons Clause|Elastic License|PolyForm",
    re.IGNORECASE,
)
LOCAL_PACKAGES = {
    "meufinanceiro-api",
    "meufinanceiro-banking",
    "meufinanceiro-persistence",
    "meufinanceiro-security",
    "meufinanceiro-worker",
}


def license_text(distribution: metadata.Distribution) -> str:
    expression = distribution.metadata.get("License-Expression")
    declared = distribution.metadata.get("License")
    classifiers = distribution.metadata.get_all("Classifier") or []
    license_classifiers = [
        item.removeprefix("License :: ")
        for item in classifiers
        if item.startswith("License :: ")
    ]
    return expression or declared or "; ".join(license_classifiers) or "UNKNOWN"


def main() -> int:
    failures: list[str] = []
    rows: list[tuple[str, str, str]] = []

    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name", "UNKNOWN")
        normalized = name.lower().replace("_", "-")
        license_value = license_text(distribution).strip()
        rows.append((name, distribution.version, license_value))
        if normalized not in LOCAL_PACKAGES and DENIED.search(license_value):
            failures.append(f"{name}=={distribution.version}: {license_value}")

    for name, version, license_value in sorted(rows, key=lambda row: row[0].lower()):
        print(f"{name}=={version}\t{license_value}")

    if failures:
        print("Known incompatible or review-required Python licenses detected:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
