#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FORMAT_NAME = "meufinanceiro-foundation-backup"
FORMAT_VERSION = 1
POSTGRES_IMAGE = "postgres:18.4-alpine"
REQUIRED_FILES = ("database.dump", "installation.env", "keyring.json")
BACKUP_ID_PATTERN = re.compile(r"^meufinanceiro-\d{8}T\d{6}Z-[0-9a-f]{8}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON inválido: {path.name}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Objeto JSON esperado: {path.name}")
    return payload


def _keyring_metadata(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    version = payload.get("version")
    active_key_id = payload.get("active_key_id")
    keys = payload.get("keys")
    if version != 1:
        raise ValueError("Versão inesperada do keyring")
    if not isinstance(active_key_id, str) or not active_key_id:
        raise ValueError("active_key_id ausente no keyring")
    if not isinstance(keys, dict) or not keys:
        raise ValueError("Coleção de chaves inválida")
    if active_key_id not in keys:
        raise ValueError("Chave ativa não existe no keyring")
    if any(not isinstance(key_id, str) or not key_id for key_id in keys):
        raise ValueError("Identificador de chave inválido")
    if any(not isinstance(value, str) or not value for value in keys.values()):
        raise ValueError("Material de chave inválido")
    return {
        "version": version,
        "active_key_id": active_key_id,
        "key_count": len(keys),
    }


def _file_metadata(path: Path) -> dict[str, Any]:
    return {"sha256": _sha256(path), "size_bytes": path.stat().st_size}


def create_manifest(args: argparse.Namespace) -> int:
    bundle_dir = Path(args.bundle_dir).resolve()
    if not bundle_dir.is_dir():
        raise ValueError("Diretório do bundle não existe")
    if not BACKUP_ID_PATTERN.fullmatch(args.backup_id):
        raise ValueError("Identificador de backup inválido")
    if not args.database_name or not args.schema_revision:
        raise ValueError("Banco e revisão Alembic são obrigatórios")

    file_paths = {name: bundle_dir / name for name in REQUIRED_FILES}
    missing = [name for name, path in file_paths.items() if not path.is_file()]
    if missing:
        raise ValueError(f"Arquivos ausentes: {', '.join(missing)}")

    manifest = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "backup_id": args.backup_id,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "sensitive": True,
        "database": {
            "name": args.database_name,
            "schema_revision": args.schema_revision,
            "dump_format": "postgresql-custom",
            "postgres_image": POSTGRES_IMAGE,
        },
        "keyring": _keyring_metadata(file_paths["keyring.json"]),
        "files": {
            name: _file_metadata(path) for name, path in file_paths.items()
        },
    }
    manifest_path = bundle_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


def validate_bundle(bundle_dir: Path) -> dict[str, Any]:
    bundle_dir = bundle_dir.resolve()
    manifest_path = bundle_dir / "manifest.json"
    if not bundle_dir.is_dir() or not manifest_path.is_file():
        raise ValueError("Bundle ou manifesto inexistente")

    manifest = _load_json(manifest_path)
    if manifest.get("format") != FORMAT_NAME or manifest.get("version") != FORMAT_VERSION:
        raise ValueError("Contrato de backup incompatível")
    backup_id = manifest.get("backup_id")
    if not isinstance(backup_id, str) or not BACKUP_ID_PATTERN.fullmatch(backup_id):
        raise ValueError("Identificador de backup inválido")
    if manifest.get("sensitive") is not True:
        raise ValueError("Bundle não está marcado como sensível")

    created_at = manifest.get("created_at")
    if not isinstance(created_at, str):
        raise ValueError("created_at ausente")
    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("created_at inválido") from exc

    database = manifest.get("database")
    if not isinstance(database, dict):
        raise ValueError("Metadados do banco ausentes")
    if database.get("dump_format") != "postgresql-custom":
        raise ValueError("Formato do dump incompatível")
    if database.get("postgres_image") != POSTGRES_IMAGE:
        raise ValueError("Imagem PostgreSQL incompatível")
    for field in ("name", "schema_revision"):
        if not isinstance(database.get(field), str) or not database[field]:
            raise ValueError(f"Campo de banco inválido: {field}")

    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(REQUIRED_FILES):
        raise ValueError("Inventário de arquivos incompatível")
    for name in REQUIRED_FILES:
        path = bundle_dir / name
        metadata = files.get(name)
        if not path.is_file() or not isinstance(metadata, dict):
            raise ValueError(f"Arquivo obrigatório ausente: {name}")
        expected_hash = metadata.get("sha256")
        expected_size = metadata.get("size_bytes")
        if not isinstance(expected_hash, str) or not SHA256_PATTERN.fullmatch(expected_hash):
            raise ValueError(f"SHA-256 inválido: {name}")
        if not isinstance(expected_size, int) or expected_size < 0:
            raise ValueError(f"Tamanho inválido: {name}")
        if path.stat().st_size != expected_size or _sha256(path) != expected_hash:
            raise ValueError(f"Integridade inválida: {name}")

    keyring = manifest.get("keyring")
    current_keyring = _keyring_metadata(bundle_dir / "keyring.json")
    if keyring != current_keyring:
        raise ValueError("Metadados do keyring não correspondem ao arquivo")

    return {
        "backup_id": backup_id,
        "database_name": database["name"],
        "schema_revision": database["schema_revision"],
        "postgres_image": database["postgres_image"],
    }


def validate_manifest(args: argparse.Namespace) -> int:
    safe = validate_bundle(Path(args.bundle_dir))
    print(json.dumps(safe, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Contrato de backup do MeuFinanceiro")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Gerar manifest.json")
    create.add_argument("--bundle-dir", required=True)
    create.add_argument("--backup-id", required=True)
    create.add_argument("--database-name", required=True)
    create.add_argument("--schema-revision", required=True)
    create.set_defaults(handler=create_manifest)

    validate = subparsers.add_parser("validate", help="Validar bundle e hashes")
    validate.add_argument("--bundle-dir", required=True)
    validate.set_defaults(handler=validate_manifest)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.handler(args)
    except ValueError as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
