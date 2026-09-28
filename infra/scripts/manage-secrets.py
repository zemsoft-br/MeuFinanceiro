#!/usr/bin/env python3
"""Initialize, validate, and rotate the local application keyring."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECURITY_SOURCE = ROOT / "packages" / "security" / "src"
sys.path.insert(0, str(SECURITY_SOURCE))

from meufinanceiro_security.errors import KeyringError  # noqa: E402
from meufinanceiro_security.keyring import (  # noqa: E402
    initialize_keyring_file,
    load_keyring,
    rotate_keyring_file,
)

DEFAULT_PATH = ROOT / ".secrets" / "keyring.json"


def validate_host_directory(path: Path) -> None:
    if os.name == "nt":
        return
    mode = path.parent.stat().st_mode & 0o777
    if mode & 0o077:
        raise KeyringError("keyring parent directory must use mode 0700")


def print_metadata(path: Path) -> None:
    keyring = load_keyring(path)
    validate_host_directory(path)
    print(f"keyring_version={keyring.version}")
    print(f"active_key_id={keyring.active_key_id}")
    print(f"retained_keys={len(keyring.keys)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "validate", "rotate"))
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()
    path = args.path.resolve()

    try:
        if args.command == "init":
            initialize_keyring_file(path)
        elif args.command == "rotate":
            rotate_keyring_file(path)
        print_metadata(path)
    except KeyringError as exc:
        print(f"secret management failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
