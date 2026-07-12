"""Plugin/extension loader resolves shorthand names and fires registration."""

from __future__ import annotations

from wat import plugins
from wat.registry import REGISTRY


def test_bundled_extension_shorthand_registers_actions():
    plugins.load(["liveview"])
    assert REGISTRY.has("wait_for_lv")
    assert REGISTRY.has("phx_push")
    # the liveview after_step settle hook is registered
    assert any(REGISTRY.hooks("after_step"))


def test_sql_and_auth_shorthands_load():
    plugins.load(["sql", "auth"])
    for name in ("sql", "docker_sql", "mix_run", "logout"):
        assert REGISTRY.has(name), name


def test_loading_twice_is_idempotent():
    # Modules are import-cached, so a second load must not raise ActionAlreadyRegistered.
    plugins.load(["liveview"])
    plugins.load(["liveview"])
