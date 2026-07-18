"""Config loader: layering and value coercion (env/TOML -> typed fields)."""

from __future__ import annotations

from wat.config import load_config, _coerce


def test_coerce_scalars():
    assert _coerce("headless", "true") is True
    assert _coerce("wait_ms", "5000") == 5000
    assert _coerce("visual_max_diff_ratio", "0.05") == 0.05


def test_coerce_list_field_splits_csv():
    # regression: list fields (extensions/plugins) from an env/TOML scalar must split on
    # commas, not become a per-character list.
    assert _coerce("extensions", "visual,sql") == ["visual", "sql"]
    assert _coerce("extensions", "visual") == ["visual"]
    assert _coerce("plugins", " a , b ,") == ["a", "b"]


def test_env_sets_extensions_list(tmp_path, monkeypatch):
    monkeypatch.setenv("WAT_EXTENSIONS", "visual,sql")
    cfg = load_config(tmp_path)
    assert cfg.extensions == ["visual", "sql"]


def test_toml_array_extensions(tmp_path):
    (tmp_path / "wat.toml").write_text('extensions = ["visual", "liveview"]\n')
    cfg = load_config(tmp_path)
    assert cfg.extensions == ["visual", "liveview"]


def test_cli_overrides_win_over_env(tmp_path, monkeypatch):
    monkeypatch.setenv("WAT_BASE_URL", "http://env")
    cfg = load_config(tmp_path, {"base_url": "http://cli"})
    assert cfg.base_url == "http://cli"
