"""Accessibility extension: verdict logic (fake page) + the real builtin JS (browser).

The unit tests drive the shipped ``assert_a11y`` handler with canned evaluate results;
one browser-backed test runs the actual injected checks against clean and violating
pages (skipped automatically when Playwright/chromium is unavailable).
"""

from __future__ import annotations

import pytest

import wat  # noqa: F401 — registers core actions
from wat.ext import a11y as A  # registers assert_a11y
from wat.config import WatConfig
from wat.errors import StepFailure
from conftest import FakePage, make_ctx


def _ctx(step, violations):
    page = FakePage(evaluate_result={"violations": violations})
    return make_ctx(step, page=page)


# -- verdict / options (fake page) ------------------------------------------

def test_clean_page_passes():
    result = A.assert_a11y(_ctx({"action": "assert_a11y"}, []))
    assert result["pass"] is True and result["count"] == 0


def test_violations_fail_with_diagnostics():
    v = [{"rule": "img-alt", "target": "img.hero", "detail": "image has no alt attribute"}]
    result = A.assert_a11y(_ctx({"action": "assert_a11y"}, v))
    assert result["pass"] is False
    assert result["count"] == 1 and result["violations"] == v
    assert "1 a11y violation" in result["reason"]


def test_allow_tolerates_up_to_n():
    v = [{"rule": "dup-id", "target": "div#x", "detail": "d"}] * 2
    assert A.assert_a11y(_ctx({"action": "assert_a11y", "allow": 2}, v))["pass"] is True
    assert A.assert_a11y(_ctx({"action": "assert_a11y", "allow": 1}, v))["pass"] is False


def test_reported_violations_are_capped():
    v = [{"rule": "label", "target": f"input#{i}", "detail": "d"} for i in range(25)]
    result = A.assert_a11y(_ctx({"action": "assert_a11y"}, v))
    assert result["count"] == 25 and len(result["violations"]) == A._MAX_REPORTED


def test_unknown_engine_rejected():
    with pytest.raises(StepFailure, match="unknown engine"):
        A.assert_a11y(_ctx({"action": "assert_a11y", "engine": "wave"}, []))


def test_axe_engine_needs_a_path():
    ctx = make_ctx({"action": "assert_a11y", "engine": "axe"}, page=FakePage())
    with pytest.raises(StepFailure, match="axe_path"):
        A.assert_a11y(ctx)


def test_scope_error_surfaces_as_flow_authoring():
    page = FakePage(evaluate_result={"error": "a11y scope not found: #nope"})
    with pytest.raises(StepFailure, match="scope not found"):
        A.assert_a11y(make_ctx({"action": "assert_a11y", "selector": "#nope"}, page=page))


# -- the real builtin JS, in a real browser ---------------------------------

_BAD_PAGE = (
    "data:text/html,<html><head><title>bad</title></head><body>"
    "<img src='x.png'>"                       # img-alt
    "<button></button>"                        # control-name
    "<input type='text'>"                      # label
    "<div id='dup'></div><div id='dup'></div>"  # dup-id
    "<a href='%23' tabindex='5'>go</a>"        # tabindex-positive
    "</body></html>"                            # html-lang (no lang attr)
)

_CLEAN_PAGE = (
    "data:text/html,<html lang='en'><head><title>ok</title></head><body>"
    "<img src='x.png' alt='logo'>"
    "<button>Save</button>"
    "<label>Email <input type='text'></label>"
    "</body></html>"
)


@pytest.fixture(scope="module")
def browser_page():
    playwright = pytest.importorskip("playwright.sync_api")
    try:
        pw = playwright.sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
    except Exception as exc:  # no browser binaries installed
        pytest.skip(f"chromium unavailable: {exc}")
    page = browser.new_page()
    yield page
    browser.close()
    pw.stop()


def test_builtin_js_flags_real_violations(browser_page):
    browser_page.goto(_BAD_PAGE)
    result = browser_page.evaluate(A._BUILTIN_JS, [None, None])
    rules = {v["rule"] for v in result["violations"]}
    assert {"img-alt", "control-name", "label", "dup-id", "tabindex-positive", "html-lang"} <= rules


def test_builtin_js_clean_page_has_no_violations(browser_page):
    browser_page.goto(_CLEAN_PAGE)
    result = browser_page.evaluate(A._BUILTIN_JS, [None, None])
    assert result["violations"] == []


def test_builtin_js_rules_filter_and_scope(browser_page):
    browser_page.goto(_BAD_PAGE)
    only_img = browser_page.evaluate(A._BUILTIN_JS, [None, ["img-alt"]])
    assert {v["rule"] for v in only_img["violations"]} == {"img-alt"}
    missing_scope = browser_page.evaluate(A._BUILTIN_JS, ["#nope", None])
    assert "scope not found" in missing_scope["error"]
