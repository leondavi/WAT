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


def test_load_plugin_from_file_path(tmp_path):
    plugin = tmp_path / "myapp_wat_plugin.py"
    plugin.write_text(
        "from wat import register_action\n"
        "@register_action('demo_app_action', group='myapp')\n"
        "def _a(ctx):\n    return True\n"
    )
    plugins.load([str(plugin)], root=tmp_path)
    assert REGISTRY.has("demo_app_action")


def test_missing_plugin_file_raises(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        plugins.load(["does/not/exist.py"], root=tmp_path)
