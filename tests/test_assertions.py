"""Assertion handlers exercised against the fake page — the real shipped code path.

Ports the intent of the old Cells ``test_wat_assertions.py`` (the {pass:false} /
{pass:true} / non-dict cases) but drives the actual ``assert_js`` handler instead of
a re-implemented stub, so the test can't drift from the runner.
"""

from __future__ import annotations

import wat  # noqa: F401 — ensures core actions are registered
from wat.actions import assertions as A
from conftest import FakePage, FakeDriver, FakeLocator, make_ctx


# -- assert_js: the {pass, reason} contract ---------------------------------

def test_assert_js_dict_pass_true():
    ctx = make_ctx({"action": "assert_js", "script": "x"},
                   page=FakePage(evaluate_result={"pass": True}))
    assert A.assert_js(ctx)["pass"] is True


def test_assert_js_dict_pass_false_carries_reason():
    ctx = make_ctx({"action": "assert_js", "script": "x"},
                   page=FakePage(evaluate_result={"pass": False, "reason": "boom"}))
    result = A.assert_js(ctx)
    assert result["pass"] is False
    assert result["reason"] == "boom"


def test_assert_js_dict_without_pass_key_is_truthy():
    ctx = make_ctx({"action": "assert_js", "script": "x"},
                   page=FakePage(evaluate_result={"note": "legacy"}))
    assert A.assert_js(ctx)["pass"] is True


def test_assert_js_non_dict_falsy_fails():
    for falsy in (False, None, 0, ""):
        ctx = make_ctx({"action": "assert_js", "script": "x"},
                       page=FakePage(evaluate_result=falsy))
        assert A.assert_js(ctx)["pass"] is False


def test_assert_js_non_dict_truthy_passes():
    for truthy in (True, 1, "ok", [1]):
        ctx = make_ctx({"action": "assert_js", "script": "x"},
                       page=FakePage(evaluate_result=truthy))
        assert A.assert_js(ctx)["pass"] is True


def test_assert_js_preserves_diagnostic_fields():
    # issue #2: extra fields on the returned object must survive for the log.
    ctx = make_ctx({"action": "assert_js", "script": "x"},
                   page=FakePage(evaluate_result={"pass": False, "why": "no textarea", "label": "c"}))
    out = A.assert_js(ctx)
    assert out["pass"] is False
    assert out["why"] == "no textarea" and out["label"] == "c"


# -- element / text ----------------------------------------------------------

def test_assert_element_present_and_absent():
    page = FakePage(locators={"#ok": FakeLocator(count=2), "#no": FakeLocator(count=0)})
    assert A.assert_element(make_ctx({"action": "assert_element", "selector": "#ok"}, page=page))["pass"]
    assert not A.assert_element(make_ctx({"action": "assert_element", "selector": "#no"}, page=page))["pass"]


def test_assert_element_text_contains():
    page = FakePage(locators={"#t": FakeLocator(text="Hello WAT")})
    ok = A.assert_element_text(make_ctx({"action": "assert_element_text", "selector": "#t", "value": "WAT"}, page=page))
    bad = A.assert_element_text(make_ctx({"action": "assert_element_text", "selector": "#t", "value": "nope"}, page=page))
    assert ok["pass"] and not bad["pass"]


def test_text_alias_is_canonicalized_to_value():
    # A flow may use "text"; the runner canonicalizes it, but assert reads "value".
    from wat.schema import canonicalize_step

    step = canonicalize_step({"action": "assert_element_text", "selector": "#t", "text": "WAT"})
    page = FakePage(locators={"#t": FakeLocator(text="Hello WAT")})
    assert A.assert_element_text(make_ctx(step, page=page))["pass"]


# -- url / console / network -------------------------------------------------

def test_assert_url_contains():
    ctx = make_ctx({"action": "assert_url_contains", "value": "/admin"},
                   page=FakePage(url="http://x/admin/users"))
    assert A.assert_url_contains(ctx)["pass"]


def test_assert_no_console_errors():
    clean = make_ctx({"action": "assert_no_console_errors"}, driver=FakeDriver(console_errors=[]))
    dirty = make_ctx({"action": "assert_no_console_errors"}, driver=FakeDriver(console_errors=["x"]))
    assert A.assert_no_console_errors(clean)["pass"]
    assert not A.assert_no_console_errors(dirty)["pass"]


def test_assert_no_network_errors():
    ctx = make_ctx({"action": "assert_no_network_errors"},
                   driver=FakeDriver(network_failures=[{"url": "u", "status": 500}]))
    assert not A.assert_no_network_errors(ctx)["pass"]
