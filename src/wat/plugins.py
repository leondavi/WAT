"""Plugin & extension loader.

Apps register custom actions/hooks by importing their plugin module — the
``@register_action``/``@register_hook`` decorators fire as a side effect. This loader
resolves two kinds of names:

    "myapp.wat_plugin"          -> import the module (decorators run on import)
    "myapp.wat_plugin:register" -> import, then call register(REGISTRY)
    "liveview" / "sql"          -> shorthand for the bundled "wat.ext.<name>"
"""

from __future__ import annotations

import importlib

from .registry import REGISTRY

# Short names for bundled extensions.
_BUNDLED = {"liveview": "wat.ext.liveview", "sql": "wat.ext.sql", "auth": "wat.ext.auth"}


def load(names: list[str]) -> None:
    """Import every plugin/extension in *names* (order preserved)."""
    for name in names:
        _load_one(name)


def _load_one(name: str) -> None:
    target = _BUNDLED.get(name, name)
    module_path, _, attr = target.partition(":")
    module = importlib.import_module(module_path)
    if attr:
        getattr(module, attr)(REGISTRY)
