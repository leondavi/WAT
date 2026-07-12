"""Assertion actions — the heart of a flow's meaning.

Every handler returns ``{"pass": bool, "reason": str | None}`` so the runner can
apply soft-assert / optional semantics uniformly. Assertions are implemented with
plain locator methods (not Playwright's ``expect``) so they can be unit-tested
against a lightweight fake page with no browser.
"""

from __future__ import annotations

import re

from ..context import StepContext
from ..registry import register_action
from .scripting import as_callable
from ._poll import poll_until


def _verdict(ok: bool, reason: str) -> dict:
    return {"pass": ok, "reason": None if ok else reason}


# -- element presence / state ------------------------------------------------

@register_action("assert_element", required=("selector",), group="assert",
                 description="At least one element matches.")
def assert_element(ctx: StepContext) -> dict:
    loc = ctx.locator()
    ok = poll_until(lambda: loc.count() > 0, ctx.timeout_ms())
    return _verdict(ok, "no element matched selector")


@register_action("assert_no_element", required=("selector",), group="assert",
                 description="No element matches.")
def assert_no_element(ctx: StepContext) -> dict:
    return _verdict(ctx.locator().count() == 0, "element unexpectedly present")


@register_action("assert_visible", required=("selector",), group="assert", description="Element is visible.")
def assert_visible(ctx: StepContext) -> dict:
    loc = ctx.locator()
    ok = poll_until(lambda: loc.is_visible(), ctx.timeout_ms())
    return _verdict(ok, "element not visible")


@register_action("assert_hidden", required=("selector",), group="assert",
                 description="Element is absent or hidden.")
def assert_hidden(ctx: StepContext) -> dict:
    loc = ctx.locator()
    return _verdict(loc.count() == 0 or not loc.is_visible(), "element is visible")


@register_action("assert_enabled", required=("selector",), group="assert", description="Element is enabled.")
def assert_enabled(ctx: StepContext) -> dict:
    return _verdict(ctx.locator().is_enabled(), "element is disabled")


@register_action("assert_disabled", required=("selector",), group="assert", description="Element is disabled.")
def assert_disabled(ctx: StepContext) -> dict:
    return _verdict(not ctx.locator().is_enabled(), "element is enabled")


@register_action("assert_checked", required=("selector",), group="assert",
                 description="Checkbox/radio is checked.")
def assert_checked(ctx: StepContext) -> dict:
    return _verdict(ctx.locator().is_checked(), "element is not checked")


# -- text / attributes / values ---------------------------------------------

@register_action("assert_element_text", required=("selector", "value"), group="assert",
                 description="Element text contains value.")
def assert_element_text(ctx: StepContext) -> dict:
    needle = str(ctx.field("value", required=True))
    loc = ctx.locator()
    ok = poll_until(lambda: needle in (loc.inner_text() or ""), ctx.timeout_ms())
    return _verdict(ok, f"element text did not contain {needle!r}")


@register_action("assert_element_count", required=("selector", "count"), group="assert",
                 description="Exactly N elements match.")
def assert_element_count(ctx: StepContext) -> dict:
    want = int(ctx.field("count", required=True))
    loc = ctx.locator()
    ok = poll_until(lambda: loc.count() == want, ctx.timeout_ms())
    return _verdict(ok, f"expected {want} elements, found {loc.count()}")


@register_action("assert_attribute", required=("selector", "attr"), group="assert",
                 description="Element attribute equals/contains value.")
def assert_attribute(ctx: StepContext) -> dict:
    attr = ctx.field("attr", required=True)
    want = str(ctx.field("value", ""))
    got = ctx.locator().get_attribute(attr) or ""
    ok = (want in got) if ctx.step.get("contains") else (got == want)
    return _verdict(ok, f"attribute {attr}={got!r} did not match {want!r}")


@register_action("assert_value", required=("selector", "value"), group="assert",
                 description="Input value equals value.")
def assert_value(ctx: StepContext) -> dict:
    want = str(ctx.field("value", required=True))
    got = ctx.locator().input_value()
    return _verdict(got == want, f"value {got!r} != {want!r}")


# -- url / title / page text -------------------------------------------------

@register_action("assert_url_contains", required=("value",), group="assert",
                 description="Current URL contains value.")
def assert_url_contains(ctx: StepContext) -> dict:
    needle = str(ctx.field("value", required=True))
    ok = poll_until(lambda: needle in ctx.page.url, ctx.timeout_ms())
    return _verdict(ok, f"url {ctx.page.url!r} did not contain {needle!r}")


@register_action("assert_url_not_contains", required=("value",), group="assert",
                 description="Current URL does not contain value.")
def assert_url_not_contains(ctx: StepContext) -> dict:
    needle = str(ctx.field("value", required=True))
    return _verdict(needle not in ctx.page.url, f"url unexpectedly contained {needle!r}")


@register_action("assert_url_matches", required=("pattern",), group="assert",
                 description="Current URL matches a regex.")
def assert_url_matches(ctx: StepContext) -> dict:
    pattern = str(ctx.field("pattern", required=True))
    ok = poll_until(lambda: re.search(pattern, ctx.page.url) is not None, ctx.timeout_ms())
    return _verdict(ok, f"url {ctx.page.url!r} did not match /{pattern}/")


@register_action("assert_title", required=("value",), group="assert", description="Page title contains value.")
def assert_title(ctx: StepContext) -> dict:
    needle = str(ctx.field("value", required=True))
    return _verdict(needle in ctx.page.title(), f"title did not contain {needle!r}")


@register_action("assert_text_contains", required=("value",), group="assert",
                 description="Page body text contains value.")
def assert_text_contains(ctx: StepContext) -> dict:
    needle = str(ctx.field("value", required=True))
    ok = poll_until(lambda: needle in _body_text(ctx), ctx.timeout_ms())
    return _verdict(ok, f"page text did not contain {needle!r}")


@register_action("assert_text_not_contains", required=("value",), group="assert",
                 description="Page body text does not contain value.")
def assert_text_not_contains(ctx: StepContext) -> dict:
    needle = str(ctx.field("value", required=True))
    return _verdict(needle not in _body_text(ctx), f"page text unexpectedly contained {needle!r}")


@register_action("assert_text_matches", required=("pattern",), group="assert",
                 description="Page body text matches a regex.")
def assert_text_matches(ctx: StepContext) -> dict:
    pattern = str(ctx.field("pattern", required=True))
    ok = poll_until(lambda: re.search(pattern, _body_text(ctx)) is not None, ctx.timeout_ms())
    return _verdict(ok, f"page text did not match /{pattern}/")


# -- console / network -------------------------------------------------------

@register_action("assert_no_console_errors", group="assert",
                 description="No console.error / uncaught page errors so far.")
def assert_no_console_errors(ctx: StepContext) -> dict:
    errs = ctx.driver.console_errors()
    return _verdict(not errs, f"console errors: {errs[:3]}")


@register_action("assert_console_match", required=("pattern",), group="assert",
                 description="Some console message matches a regex.")
def assert_console_match(ctx: StepContext) -> dict:
    pattern = str(ctx.field("pattern", required=True))
    matches = ctx.driver.console_matches(pattern)
    return _verdict(bool(matches), f"no console message matched /{pattern}/")


@register_action("assert_no_network_errors", group="assert",
                 description="No 4xx/5xx or failed requests so far.")
def assert_no_network_errors(ctx: StepContext) -> dict:
    fails = ctx.driver.network_failures
    return _verdict(not fails, f"network failures: {fails[:3]}")


# -- JavaScript assertion ----------------------------------------------------

@register_action("assert_js", required=("script",), group="assert",
                 description="Evaluate JS; pass on truthy or {pass:true}. Promise-aware.")
def assert_js(ctx: StepContext) -> dict:
    result = ctx.page.evaluate(as_callable(str(ctx.field("script", required=True))))
    if isinstance(result, dict):
        verdict = result.get("pass", True)
        return {"pass": verdict is not False, "reason": result.get("reason")}
    return _verdict(bool(result), f"assert_js returned {result!r}")


def _body_text(ctx: StepContext) -> str:
    try:
        return ctx.page.locator("body").inner_text() or ""
    except Exception:
        return ctx.page.content() or ""
