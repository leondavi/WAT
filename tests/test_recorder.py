"""Flow recorder: pure step aggregation + a real recorded session in a browser.

The browser test drives a page with programmatic (trusted) events through an attached
recorder and validates the resulting draft flow with the real validator.
"""

from __future__ import annotations

import time

import pytest

import wat  # noqa: F401 — registers core actions (for validate_file)
from wat.recorder import Recorder, attach, _RECORDER_JS  # noqa: F401
from wat.schema import validate_file


# -- pure aggregation --------------------------------------------------------

def test_events_map_to_canonical_steps():
    r = Recorder()
    r.on_event({"kind": "click", "by": "testid", "selector": "save"})
    r.on_event({"kind": "type", "by": "css", "selector": "#email", "value": "a@b.com"})
    r.on_event({"kind": "press", "by": "css", "selector": "#email", "value": "Enter"})
    assert r.steps == [
        {"action": "click", "by": "testid", "selector": "save"},
        {"action": "type", "selector": "#email", "value": "a@b.com"},   # css omitted (default)
        {"action": "press", "selector": "#email", "value": "Enter"},
    ]


def test_typing_coalesces_to_final_value():
    r = Recorder()
    for v in ("a", "ab", "abc"):
        r.on_event({"kind": "type", "by": "css", "selector": "#q", "value": v})
    assert r.steps == [{"action": "type", "selector": "#q", "value": "abc"}]


def test_click_subsumed_by_resulting_change():
    r = Recorder()
    r.on_event({"kind": "click", "by": "css", "selector": "#agree"})
    r.on_event({"kind": "check", "by": "css", "selector": "#agree"})
    assert r.steps == [{"action": "check", "selector": "#agree"}]


def test_role_name_carried_through():
    r = Recorder()
    r.on_event({"kind": "click", "by": "role", "selector": "button", "name": "Log in"})
    assert r.steps == [{"action": "click", "by": "role", "selector": "button", "name": "Log in"}]


def test_first_navigation_is_open_and_relativized():
    r = Recorder(base_url="http://localhost:4000")
    r.on_navigation("http://localhost:4000/inbox")
    assert r.steps == [{"action": "open", "url": "/inbox"}]


def test_navigation_echo_after_click_is_dropped():
    r = Recorder(base_url="http://x")
    r.on_navigation("http://x/")                                   # open
    r.on_event({"kind": "click", "by": "css", "selector": "#go"})  # interaction now
    r.on_navigation("http://x/next")                               # immediate echo -> dropped
    assert [s["action"] for s in r.steps] == ["open", "click"]


def test_deliberate_navigation_is_kept():
    r = Recorder(base_url="http://x")
    r.on_navigation("http://x/")
    r._last_interaction = time.monotonic() - 10  # long-idle: user typed a URL
    r.on_navigation("http://x/other")
    assert r.steps[-1] == {"action": "navigate", "url": "/other"}


def test_save_writes_a_valid_draft_flow(tmp_path):
    r = Recorder()
    r.on_navigation("http://app/")
    r.on_event({"kind": "type", "by": "css", "selector": "#q", "value": "hi"})
    out = r.save(tmp_path / "fl_draft.json")
    assert validate_file(out) == []
    assert "DRAFT" in out.read_text()


# -- end-to-end: record a real session --------------------------------------

_PAGE = (
    "data:text/html,<html lang='en'><head><title>rec</title></head><body>"
    "<input id='email' type='text'>"
    "<select name='plan'><option value='a'>A</option><option value='b'>B</option></select>"
    "<input type='checkbox' data-testid='agree'>"
    "<button id='go'>Go</button>"
    "</body></html>"
)


def test_recorded_session_produces_valid_flow(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    try:
        pw = playwright.sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
    except Exception as exc:
        pytest.skip(f"chromium unavailable: {exc}")
    try:
        recorder = Recorder()
        context = browser.new_context()
        attach(context, recorder)
        page = context.new_page()
        page.goto(_PAGE)
        page.fill("#email", "a@b.com")
        page.select_option("select[name='plan']", "b")
        page.check("[data-testid='agree']")
        page.click("#go")
        page.wait_for_timeout(200)  # let bindings flush
    finally:
        browser.close()
        pw.stop()

    actions = [(s["action"], s.get("selector")) for s in recorder.steps]
    assert actions[0][0] == "open"
    assert ("type", "#email") in actions
    assert ("select_option", "select[name='plan']") in actions
    assert ("check", "agree") in actions          # via data-testid
    assert ("click", "#go") in actions
    # check came from testid inference
    check = next(s for s in recorder.steps if s["action"] == "check")
    assert check.get("by") == "testid"
    # the saved draft validates cleanly against the real registry
    out = recorder.save(tmp_path / "fl_recorded.json")
    assert validate_file(out) == []
