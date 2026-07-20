#!/usr/bin/env python3
"""Validate the Flutter Web source and generated PWA/runtime contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE_WEB = ROOT / "apps" / "app" / "web"
DEFAULT_BUILD_WEB = ROOT / "apps" / "app" / "build" / "web"

REQUIRED_BUILD_FILES = (
    "app_bootstrap.js",
    "favicon.png",
    "flutter.js",
    "flutter_bootstrap.js",
    "index.html",
    "main.dart.js",
    "manifest.json",
    "sw.js",
    "version.json",
)
REQUIRED_ICON_PATHS = (
    "icons/Icon-192.png",
    "icons/Icon-512.png",
    "icons/Icon-maskable-192.png",
    "icons/Icon-maskable-512.png",
)
FORBIDDEN_RUNTIME_ORIGINS = (
    "https://www.gstatic.com",
    "https://fonts.googleapis.com",
    "https://fonts.gstatic.com",
    "https://storage.googleapis.com",
)
API_EXCLUSION = "url.pathname === '/api' || url.pathname.startsWith('/api/')"


class FlutterWebContractError(RuntimeError):
    """Raised when the Web/PWA contract is incomplete or unsafe."""


def read_text(path: Path) -> str:
    """Read one UTF-8 contract file with an actionable failure."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FlutterWebContractError(f"required file not found: {path}") from exc


def read_json_object(path: Path) -> dict[str, Any]:
    """Read one JSON object."""
    try:
        payload: Any = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise FlutterWebContractError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise FlutterWebContractError(f"{path} must contain a JSON object")
    return payload


def require_fragments(path: Path, fragments: tuple[str, ...]) -> str:
    """Require all exact contract fragments in a text file."""
    content = read_text(path)
    missing = [fragment for fragment in fragments if fragment not in content]
    if missing:
        detail = ", ".join(repr(fragment) for fragment in missing)
        raise FlutterWebContractError(f"{path} is missing required fragments: {detail}")
    return content


def validate_manifest(path: Path) -> None:
    """Validate installability metadata and local icon declarations."""
    manifest = read_json_object(path)
    expected = {
        "name": "MeuFinanceiro",
        "short_name": "MeuFinanceiro",
        "lang": "pt-BR",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#F7F9F8",
        "theme_color": "#123B2D",
        "prefer_related_applications": False,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise FlutterWebContractError(
                f"{path}: expected {key}={value!r}, found {manifest.get(key)!r}"
            )

    icons = manifest.get("icons")
    if not isinstance(icons, list):
        raise FlutterWebContractError(f"{path}: icons must be a list")
    declared_paths = {
        icon.get("src")
        for icon in icons
        if isinstance(icon, dict) and isinstance(icon.get("src"), str)
    }
    missing_icons = sorted(set(REQUIRED_ICON_PATHS) - declared_paths)
    if missing_icons:
        raise FlutterWebContractError(
            f"{path}: missing required PWA icons: {', '.join(missing_icons)}"
        )


def validate_index(path: Path) -> None:
    """Validate manifest metadata and the versioned application loader."""
    require_fragments(
        path,
        (
            '<html lang="pt-BR">',
            '<meta name="theme-color" content="#123B2D">',
            '<link rel="manifest" href="manifest.json">',
            '<script src="app_bootstrap.js"></script>',
        ),
    )


def validate_app_bootstrap(path: Path) -> None:
    """Validate early worker activation and deferred Flutter bootstrap."""
    require_fragments(
        path,
        (
            "const waitForController = async () =>",
            "navigator.serviceWorker.addEventListener('controllerchange'",
            "const loadFlutter = () =>",
            "script.src = 'flutter_bootstrap.js'",
            "navigator.serviceWorker.register('sw.js'",
            "updateViaCache: 'none'",
            "registration.update()",
            "navigator.serviceWorker.ready",
            "await waitForController()",
            "loadFlutter()",
        ),
    )


def validate_service_worker(path: Path) -> None:
    """Validate cache isolation, update strategy and API exclusion."""
    content = require_fragments(
        path,
        (
            "const CACHE_PREFIX = 'meufinanceiro-flutter-shell-'",
            "const MANAGED_CACHE_PREFIXES = [CACHE_PREFIX, 'meufinanceiro-shell-']",
            "'/app_bootstrap.js'",
            "request.method !== 'GET'",
            "url.origin !== self.location.origin",
            API_EXCLUSION,
            "request.mode === 'navigate'",
            "const cache = await caches.open(CACHE_NAME)",
            "fetch(request, { cache: 'no-store' })",
            "storeSuccessfulResponse(cache, cacheKey, response)",
            "response.ok",
            "response.type !== 'basic'",
            "await cache.match(cacheKey)",
            "await cache.match(fallbackPath)",
            "MANAGED_CACHE_PREFIXES.some((prefix) => key.startsWith(prefix))",
            "caches.delete(key)",
            ".then(() => self.skipWaiting())",
            "self.clients.claim()",
            "networkFirst(request, '/index.html', '/index.html')",
        ),
    )

    api_index = content.index(API_EXCLUSION)
    respond_index = content.index("event.respondWith")
    if api_index > respond_index:
        raise FlutterWebContractError(
            f"{path}: /api boundary must be evaluated before respondWith"
        )

    forbidden = (
        "/api/v1/health",
        "Authorization",
        "localStorage",
        "flutter_service_worker.js",
        "caches.match(",
        "'/sw.js'",
        "cache.put(request",
    )
    present = [fragment for fragment in forbidden if fragment in content]
    if present:
        raise FlutterWebContractError(
            f"{path}: unsafe or legacy fragments present: {', '.join(present)}"
        )


def validate_no_remote_runtime_resources(build_dir: Path) -> None:
    """Reject generated bootstrap configuration that depends on public CDNs."""
    for relative in ("index.html", "app_bootstrap.js", "flutter_bootstrap.js"):
        path = build_dir / relative
        content = read_text(path)
        found = [origin for origin in FORBIDDEN_RUNTIME_ORIGINS if origin in content]
        if found:
            raise FlutterWebContractError(
                f"{path}: remote runtime origins are forbidden: {', '.join(found)}"
            )


def validate_source(source_dir: Path = SOURCE_WEB) -> None:
    """Validate the versioned Flutter Web source files."""
    validate_index(source_dir / "index.html")
    validate_app_bootstrap(source_dir / "app_bootstrap.js")
    validate_manifest(source_dir / "manifest.json")
    validate_service_worker(source_dir / "sw.js")


def validate_build(build_dir: Path = DEFAULT_BUILD_WEB) -> None:
    """Validate the release artifact produced by the pinned Flutter SDK."""
    missing = [
        relative
        for relative in (*REQUIRED_BUILD_FILES, *REQUIRED_ICON_PATHS)
        if not (build_dir / relative).is_file()
    ]
    if missing:
        raise FlutterWebContractError(
            f"{build_dir}: missing generated Web files: {', '.join(missing)}"
        )

    legacy_worker = build_dir / "flutter_service_worker.js"
    if legacy_worker.exists():
        raise FlutterWebContractError(
            f"{legacy_worker} must not exist; the project owns sw.js explicitly"
        )

    validate_index(build_dir / "index.html")
    validate_app_bootstrap(build_dir / "app_bootstrap.js")
    validate_manifest(build_dir / "manifest.json")
    validate_service_worker(build_dir / "sw.js")
    validate_no_remote_runtime_resources(build_dir)

    for relative in ("app_bootstrap.js", "sw.js"):
        source = read_text(SOURCE_WEB / relative)
        built = read_text(build_dir / relative)
        if built != source:
            raise FlutterWebContractError(
                f"{build_dir / relative} differs from the versioned source"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-only",
        action="store_true",
        help="Validate only versioned files and skip build/web.",
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=DEFAULT_BUILD_WEB,
        help="Flutter Web release directory.",
    )
    args = parser.parse_args()

    try:
        validate_source()
        if not args.source_only:
            validate_build(args.build_dir.resolve())
    except FlutterWebContractError as exc:
        print(f"Flutter Web contract validation failed: {exc}", file=sys.stderr)
        return 1

    scope = "source" if args.source_only else f"source and {args.build_dir}"
    print(f"Flutter Web contract validation passed: {scope}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
