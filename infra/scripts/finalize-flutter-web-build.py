#!/usr/bin/env python3
"""Finalize the Flutter Web artifact before validation or packaging."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

LEGACY_WORKER_NAME = "flutter_service_worker.js"


class FlutterWebFinalizationError(RuntimeError):
    """Raised when a generated artifact cannot be finalized safely."""


def default_build_dir(script_path: Path = Path(__file__)) -> Path:
    """Resolve the repository build directory when running from the source tree."""
    resolved = script_path.resolve()
    try:
        root = resolved.parents[2]
    except IndexError as exc:
        raise FlutterWebFinalizationError(
            "cannot infer the repository root; pass --build-dir explicitly"
        ) from exc
    return root / "apps" / "app" / "build" / "web"


def remove_empty_legacy_worker(build_dir: Path) -> bool:
    """Remove Flutter's disabled legacy worker, rejecting non-empty output."""
    worker = build_dir / LEGACY_WORKER_NAME
    if not worker.exists():
        return False
    if not worker.is_file():
        raise FlutterWebFinalizationError(f"legacy worker path is not a file: {worker}")

    size = worker.stat().st_size
    if size != 0:
        raise FlutterWebFinalizationError(
            f"{worker} contains {size} bytes despite --pwa-strategy=none"
        )

    worker.unlink()
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--build-dir",
        type=Path,
        help="Flutter Web release directory. Defaults to the repository build output.",
    )
    args = parser.parse_args()

    try:
        build_dir = (args.build_dir or default_build_dir()).resolve()
    except FlutterWebFinalizationError as exc:
        print(f"Flutter Web finalization failed: {exc}", file=sys.stderr)
        return 1

    if not build_dir.is_dir():
        print(
            f"Flutter Web finalization failed: build directory not found: {build_dir}",
            file=sys.stderr,
        )
        return 1

    try:
        removed = remove_empty_legacy_worker(build_dir)
    except FlutterWebFinalizationError as exc:
        print(f"Flutter Web finalization failed: {exc}", file=sys.stderr)
        return 1

    state = "removed empty legacy worker" if removed else "no legacy worker present"
    print(f"Flutter Web artifact finalized: {state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
