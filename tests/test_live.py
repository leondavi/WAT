"""Comprehensive tests for live (headed) browser support and its logging.

Covers the pure launch-kwargs builder, the live-mode config derivations, the
driver's live console/error streaming, and the CLI flag mapping — all without
launching a real browser.
"""

from __future__ import annotations

import types

from wat.config import WatConfig
from wat.driver import Driver, build_launch_kwargs
from wat.cli import build_parser, _overrides


# ---------------------------------------------------------------------------
# build_launch_kwargs — pure launch configuration
# ---------------------------------------------------------------------------

def test_default_is_headless_chromium():
    kind, kw = build_launch_kwargs(WatConfig())
    assert kind == "chromium"
    assert kw == {"headless": True}


def test_headed_sets_headless_false():
    _, kw = build_launch_kwargs(WatConfig(headless=False))
    assert kw["headless"] is False


def test_slow_mo_included_when_positive():
    _, kw = build_launch_kwargs(WatConfig(slow_mo_ms=250))
    assert kw["slow_mo"] == 250
    assert "slow_mo" not in build_launch_kwargs(WatConfig(slow_mo_ms=0))[1]


def test_devtools_only_when_headed_chromium():
    assert "devtools" not in build_launch_kwargs(WatConfig(devtools=True, headless=True))[1]
    assert build_launch_kwargs(WatConfig(devtools=True, headless=False))[1]["devtools"] is True
    # firefox never gets devtools
    assert "devtools" not in build_launch_kwargs(
        WatConfig(browser="firefox", devtools=True, headless=False))[1]


def test_channel_defaults_and_override():
    assert build_launch_kwargs(WatConfig(browser="chrome"))[1]["channel"] == "chrome"
    assert build_launch_kwargs(WatConfig(browser="edge"))[1]["channel"] == "msedge"
    assert build_launch_kwargs(WatConfig(channel="chrome-beta"))[1]["channel"] == "chrome-beta"
    assert "channel" not in build_launch_kwargs(WatConfig(browser="firefox"))[1]


def test_firefox_kind():
    assert build_launch_kwargs(WatConfig(browser="firefox"))[0] == "firefox"
    assert build_launch_kwargs(WatConfig(browser="webkit"))[0] == "webkit"


def test_viewport_defaults_and_override():
    assert (WatConfig().viewport_width, WatConfig().viewport_height) == (1440, 1024)
    cfg = WatConfig(viewport_width=800, viewport_height=600)
    assert cfg.viewport_width == 800 and cfg.viewport_height == 600


# ---------------------------------------------------------------------------
# Live-mode config derivations
# ---------------------------------------------------------------------------

def test_is_live():
    assert WatConfig().is_live() is False
    assert WatConfig(headless=False).is_live() is True
    assert WatConfig(slow_mo_ms=100).is_live() is True


def test_stream_console_auto_and_explicit():
    assert WatConfig(headless=False).stream_console_effective() is True   # auto on when live
    assert WatConfig().stream_console_effective() is False                # auto off when headless
    assert WatConfig(stream_console=True).stream_console_effective() is True
    assert WatConfig(headless=False, stream_console=False).stream_console_effective() is False


def test_verbose_steps_auto_and_explicit():
    assert WatConfig(slow_mo_ms=50).verbose_steps_effective() is True
    assert WatConfig().verbose_steps_effective() is False
    assert WatConfig(verbose_steps=True).verbose_steps_effective() is True


# ---------------------------------------------------------------------------
# Driver live streaming (no browser)
# ---------------------------------------------------------------------------

class _RecordingLog:
    def __init__(self):
        self.browser_lines: list[str] = []

    def wat(self, *a, **k): pass
    def browser(self, msg): self.browser_lines.append(msg)
    def app(self, *a, **k): pass


def _console_msg(mtype, text):
    return types.SimpleNamespace(type=mtype, text=text)


def test_console_error_streamed_live_when_enabled():
    log = _RecordingLog()
    d = Driver(WatConfig(headless=False), log)
    d._stream = True
    d._on_console(_console_msg("error", "boom"))
    d._on_console(_console_msg("log", "chatter"))   # non-error: not streamed
    assert log.browser_lines == ["console.error: boom"]
    # still buffered for assertions
    assert d.console_errors() == ["boom"]


def test_console_not_streamed_when_disabled():
    log = _RecordingLog()
    d = Driver(WatConfig(), log)  # headless -> stream off
    d._stream = False
    d._on_console(_console_msg("error", "boom"))
    assert log.browser_lines == []
    assert d.console_errors() == ["boom"]  # still captured


def test_pageerror_streamed_live():
    log = _RecordingLog()
    d = Driver(WatConfig(headless=False), log)
    d._stream = True
    d._on_pageerror("TypeError: x")
    assert any("pageerror: TypeError" in line for line in log.browser_lines)


def test_drain_is_noop_when_streaming():
    log = _RecordingLog()
    d = Driver(WatConfig(headless=False), log)
    d._stream = True
    d.console_messages.append({"type": "error", "text": "already-streamed"})
    d.drain_diagnostics()
    assert log.browser_lines == []  # not re-logged


# ---------------------------------------------------------------------------
# CLI flag mapping
# ---------------------------------------------------------------------------

def _ov(argv):
    return _overrides(build_parser().parse_args(argv))


def test_cli_channel_and_pause_and_trace():
    ov = _ov(["--all", "--channel", "chrome", "--pause-on-failure", "--trace", "on"])
    assert ov["channel"] == "chrome"
    assert ov["pause_on_failure"] is True
    assert ov["trace"] == "on"


def test_cli_stream_console_flag():
    assert _ov(["--all", "--stream-console"])["stream_console"] is True


def test_cli_live_still_headed_slowmo():
    ov = _ov(["--all", "--live"])
    assert ov["headless"] is False and ov["slow_mo_ms"] == 250
