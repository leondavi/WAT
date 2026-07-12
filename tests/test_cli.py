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
