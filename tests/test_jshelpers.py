"""Shared per-app JS helpers (config ``helpers``): resolution, injection, validation.

The pure pieces run with no browser; one end-to-end test proves the helpers survive a
navigation in real Chromium (skipped automatically when it is unavailable).
"""

from __future__ import annotations

import shutil

import pytest

from wat import jshelpers as H
from wat.config import WatConfig
from wat.driver import Driver
from wat.errors import SOURCE_FLOW_AUTHORING, StepFailure

_HELPERS_JS = ("const double = x => x * 2;  // private to the helpers file\n"
               "window.watDouble = x => double(x);\nwindow.WAT_TAG = 'shared';\n")


def _cfg(tmp_path, helpers="flows/helpers.js", body=_HELPERS_JS):
    if body is not None:
        (tmp_path / "flows").mkdir(exist_ok=True)
        (tmp_path / "flows" / "helpers.js").write_text(body, encoding="utf-8")
    return WatConfig(root=str(tmp_path), helpers=helpers)


def test_not_configured_is_a_noop(tmp_path):
    cfg = WatConfig(root=str(tmp_path))
    assert H.helpers_path(cfg) is None
    assert H.init_script(cfg) is None
    assert H.validate_helpers(cfg) == []


def test_path_resolves_against_root(tmp_path):
    cfg = _cfg(tmp_path)
    assert H.helpers_path(cfg) == tmp_path / "flows" / "helpers.js"


def test_init_script_is_source_plus_source_url(tmp_path):
    script = H.init_script(_cfg(tmp_path))
    assert script.startswith(_HELPERS_JS)
    assert "//# sourceURL=wat-helpers/helpers.js" in script


def test_init_script_missing_file_is_flow_authoring_failure(tmp_path):
    with pytest.raises(StepFailure) as exc:
        H.init_script(_cfg(tmp_path, body=None))
    assert exc.value.source == SOURCE_FLOW_AUTHORING


def test_validate_reports_missing_file(tmp_path):
    errors = H.validate_helpers(_cfg(tmp_path, body=None))
    assert len(errors) == 1 and "not found" in errors[0]


def test_validate_ok_without_node(tmp_path, monkeypatch):
    monkeypatch.setattr(H.shutil, "which", lambda _name: None)
    assert H.validate_helpers(_cfg(tmp_path, body="function ( {")) == []  # no node: no syntax check


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_validate_reports_syntax_error_with_node(tmp_path):
    assert H.validate_helpers(_cfg(tmp_path)) == []
    errors = H.validate_helpers(_cfg(tmp_path, body="function broken( {\n"))
    assert len(errors) == 1 and "SyntaxError" in errors[0]


class _RecordingContext:
    def __init__(self):
        self.scripts: list[str] = []

    def add_init_script(self, script: str) -> None:
        self.scripts.append(script)


class _Log:
    def __init__(self):
        self.lines: list[str] = []

    def wat(self, message, level="info"):
        self.lines.append(message)


def test_driver_registers_helpers_on_the_context(tmp_path):
    log = _Log()
    driver = Driver(_cfg(tmp_path), log)
    driver.context = _RecordingContext()
    driver._inject_helpers()
    assert len(driver.context.scripts) == 1 and "watDouble" in driver.context.scripts[0]
    assert any("injecting JS helpers" in line for line in log.lines)


def test_driver_without_helpers_registers_nothing(tmp_path):
    driver = Driver(WatConfig(root=str(tmp_path)), _Log())
    driver.context = _RecordingContext()
    driver._inject_helpers()
    assert driver.context.scripts == []


def test_cli_validate_fails_on_missing_helpers(tmp_path, capsys):
    from wat.cli import main

    (tmp_path / "flows").mkdir()
    (tmp_path / "flows" / "fl_ok.json").write_text(
        '{"name": "ok", "steps": [{"action": "open", "url": "/"}]}')
    (tmp_path / "wat.toml").write_text('helpers = "flows/missing.js"\n')
    rc = main(["--validate-only", "--all", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1 and "[FAIL] helpers" in out and "not found" in out


def test_cli_validate_passes_with_helpers(tmp_path, capsys, monkeypatch):
    from wat.cli import main

    monkeypatch.setattr(H.shutil, "which", lambda _name: None)
    _cfg(tmp_path)
    (tmp_path / "flows" / "fl_ok.json").write_text(
        '{"name": "ok", "steps": [{"action": "open", "url": "/"}]}')
    (tmp_path / "wat.toml").write_text('helpers = "flows/helpers.js"\n')
    rc = main(["--validate-only", "--all", "--root", str(tmp_path)])
    assert rc == 0 and "[PASS] helpers" in capsys.readouterr().out


def test_helpers_survive_navigation_in_real_browser(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    try:
        pw = playwright.sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
    except Exception as exc:  # no browser binaries installed
        pytest.skip(f"chromium unavailable: {exc}")
    try:
        context = browser.new_context()
        context.add_init_script(H.init_script(_cfg(tmp_path)))
        page = context.new_page()
        for name in ("one", "two"):  # a second navigation = a fresh window
            doc = tmp_path / f"{name}.html"
            doc.write_text(f"<p>{name}</p>", encoding="utf-8")
            page.goto(doc.as_uri())  # init scripts do not run on data: URLs
            assert page.evaluate("() => watDouble(21)") == 42
            assert page.evaluate("() => window.WAT_TAG") == "shared"
            assert page.evaluate("() => typeof double") == "undefined"  # locals stay private
    finally:
        browser.close()
        pw.stop()
