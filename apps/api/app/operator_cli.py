"""Local-only bootstrap CLI for the first installation administrator."""

from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Sequence

from meufinanceiro_persistence import (
    IdentityBootstrapConflictError,
    IdentityPersistenceError,
    OperatorIdentityStore,
    normalize_operator_login,
)
from meufinanceiro_security.passwords import PasswordService

from app.core.config import get_settings
from app.core.database import create_database
from app.services.operator_auth import validate_operator_password


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.operator_cli")
    subcommands = parser.add_subparsers(dest="command", required=True)
    bootstrap = subcommands.add_parser("bootstrap")
    bootstrap.add_argument("--login", required=True)
    return parser


def _read_password() -> str:
    if not sys.stdin.isatty():
        raise RuntimeError("operator bootstrap requires an interactive terminal")
    password = getpass.getpass("Operator password: ")
    confirmation = getpass.getpass("Confirm operator password: ")
    if password != confirmation:
        raise ValueError("password confirmation does not match")
    return validate_operator_password(password)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command != "bootstrap":
        return 2
    try:
        login_name = normalize_operator_login(arguments.login)
        password = _read_password()
    except (RuntimeError, TypeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2

    settings = get_settings()
    database = create_database(settings)
    try:
        record = OperatorIdentityStore(database.engine).bootstrap_installation_admin(
            login_name=login_name,
            password_hash=PasswordService().hash(password),
        )
    except IdentityBootstrapConflictError:
        print("installation administrator already exists", file=sys.stderr)
        return 3
    except IdentityPersistenceError:
        print("installation administrator could not be created", file=sys.stderr)
        return 4
    finally:
        password = ""
        database.dispose()

    print(f"installation_id={record.installation_id}")
    print(f"operator_id={record.operator_id}")
    print(f"login={record.login_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
