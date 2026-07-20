#!/usr/bin/env python3
"""Finalize the Flutter Web artifact before validation or packaging."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUILD_DIR = ROOT / "apps" / "app" / "build" / "web"
LEGACY_WORKER_NAME = "flutter_service_worker.js"


class FlutterWebFinalizationError(RuntimeError):
    """Raised when a generated artifact cannot be finalized safely."""


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
        default=DEFAULT_BUILD_DIR,
        help="Flutter Web release directory.",
    )
    args = parser.parse_args()
    build_dir = args.build_dir.resolve()

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
