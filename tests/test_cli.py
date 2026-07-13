"""CLI argument -> config override mapping (esp. live/headed browser modes)."""

from __future__ import annotations

from wat.cli import build_parser, _overrides


def _parse(argv):
    return _overrides(build_parser().parse_args(argv))


def test_unset_flags_do_not_override():
    assert _parse(["--flow", "fl_x.json"]) == {}


def test_headed_sets_headless_false():
    assert _parse(["--all", "--headed"])["headless"] is False


def test_live_is_headed_with_slow_mo():
    ov = _parse(["--all", "--live"])
    assert ov["headless"] is False
    assert ov["slow_mo_ms"] == 250


def test_live_respects_explicit_slow_mo():
    ov = _parse(["--all", "--live", "--slow-mo", "1000"])
    assert ov["slow_mo_ms"] == 1000


def test_explicit_headless_wins_over_live():
    ov = _parse(["--all", "--live", "--headless"])
    assert ov["headless"] is True


def test_browser_and_wait_overrides():
    ov = _parse(["--all", "--browser", "firefox", "--wait-ms", "5000"])
    assert ov["browser"] == "firefox" and ov["wait_ms"] == 5000


def test_doctor_reports_extensions_and_hooks(tmp_path, capsys):
    from wat.cli import main

    (tmp_path / "wat.toml").write_text('extensions = ["liveview"]\n')
    rc = main(["--doctor", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert "extensions" in out and "liveview  ok" in out
    assert "hooks" in out and "reset hook" in out
    assert rc == 0  # playwright installed in the test venv


def test_doctor_flags_broken_plugin(tmp_path, capsys):
    from wat.cli import main

    (tmp_path / "wat.toml").write_text('plugins = ["nope.py"]\n')
    rc = main(["--doctor", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert "nope.py  FAILED" in out
    assert rc == 1  # a broken plugin makes doctor fail


def test_workers_and_fail_fast_and_report_flags():
    ov = _parse(["--all", "--workers", "4", "--fail-fast"])
    assert ov["workers"] == 4 and ov["fail_fast"] is True


def test_no_emojis_in_cli_or_installer():
    import re
    from pathlib import Path

    emoji = re.compile("[\U0001F000-\U0001FAFF☀-➿✅❌⚠✓✗]")
    root = Path(__file__).resolve().parent.parent
    for rel in ["src/wat/cli.py", "install.py", "src/wat/logging.py"]:
        assert not emoji.search((root / rel).read_text(encoding="utf-8")), f"emoji in {rel}"
