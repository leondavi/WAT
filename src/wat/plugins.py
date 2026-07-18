"""Plugin & extension loader.

Apps register custom actions/hooks by importing their plugin — the
``@register_action``/``@register_hook`` decorators fire as a side effect. This loader
resolves several name forms:

    "liveview" / "sql"          -> bundled extension "wat.ext.<name>"
    "myapp.wat_plugin"          -> import the module (decorators run on import)
    "myapp.wat_plugin:register" -> import, then call register(REGISTRY)
    "tools/WAT/app_plugin.py"   -> load from a file path (resolved against `root`)

The file-path form is the easiest way to wire an app plugin that lives in the app
repo without making it an importable package.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path

from .registry import REGISTRY

# Short names for bundled extensions.
_BUNDLED = {"liveview": "wat.ext.liveview", "sql": "wat.ext.sql", "auth": "wat.ext.auth",
            "visual": "wat.ext.visual", "a11y": "wat.ext.a11y"}


def load(names: list[str], root: str | Path = ".") -> None:
    """Import every plugin/extension in *names* (order preserved).

    *root* is the app root used to resolve relative file-path plugins.
    """
    for name in names:
        _load_one(name, Path(root))


def load_reporting(names: list[str], root: str | Path = ".") -> list[tuple[str, bool, str | None]]:
    """Like :func:`load`, but never raises — returns ``(name, ok, error)`` per entry.

    Used by ``wat --doctor`` so a broken plugin/extension is reported as a wiring
    failure instead of crashing the CLI.
    """
    results: list[tuple[str, bool, str | None]] = []
    for name in names:
        try:
            _load_one(name, Path(root))
            results.append((name, True, None))
        except Exception as exc:  # noqa: BLE001 — surface any import/registration error
            results.append((name, False, f"{type(exc).__name__}: {exc}"))
    return results


def _load_one(name: str, root: Path) -> None:
    if name in _BUNDLED:
        importlib.import_module(_BUNDLED[name])
        return

    if name.endswith(".py") or os.sep in name or "/" in name:
        _load_from_path(name, root)
        return

    module_path, _, attr = name.partition(":")
    module = importlib.import_module(module_path)
    if attr:
        getattr(module, attr)(REGISTRY)


def _load_from_path(name: str, root: Path) -> None:
    """Load a plugin module from a .py file, adding its dir to sys.path so it can
    import sibling helpers."""
    path = Path(name)
    if not path.is_absolute():
        path = (root / path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"plugin file not found: {path}")
    parent = str(path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load plugin from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
