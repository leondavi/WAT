"""Navigation & waiting actions.

Playwright auto-waits for actionability before interactions, so most flows need far
fewer explicit waits than the Selenium forks did. The wait_* actions remain for the
cases where you must synchronize on page state that isn't tied to a click/fill.
"""

from __future__ import annotations

from ..context import StepContext
from ..registry import register_action
from ._poll import poll_until


@register_action("open", required=("url",), group="navigation",
                 description="Navigate to base_url + url (typically step 0).")
def open_(ctx: StepContext) -> None:
    ctx.page.goto(ctx.url(ctx.field("url", required=True)))


@register_action("navigate", aliases=("goto",), required=("url",), group="navigation",
                 description="Mid-flow navigation to base_url + url.")
def navigate(ctx: StepContext) -> None:
    ctx.page.goto(ctx.url(ctx.field("url", required=True)))


@register_action("back", group="navigation", description="Browser back.")
def back(ctx: StepContext) -> None:
    ctx.page.go_back()


@register_action("forward", group="navigation", description="Browser forward.")
def forward(ctx: StepContext) -> None:
    ctx.page.go_forward()


@register_action("reload", group="navigation", description="Reload the current page.")
def reload(ctx: StepContext) -> None:
    ctx.page.reload()


@register_action("sleep", required=("seconds",), group="navigation",
                 description="Fixed wait in seconds (discouraged; prefer wait_for/assert).")
def sleep(ctx: StepContext) -> None:
    ctx.page.wait_for_timeout(float(ctx.field("seconds", required=True)) * 1000)


@register_action("scroll_to", required=("selector",), group="navigation",
                 description="Scroll the element into view.")
def scroll_to(ctx: StepContext) -> None:
    ctx.locator().scroll_into_view_if_needed(timeout=ctx.timeout_ms())


@register_action("wait_for", required=("selector",), group="navigation",
                 description="Wait for the selector to reach a state (default visible).")
def wait_for(ctx: StepContext) -> None:
    state = ctx.step.get("state", "visible")
    ctx.locator().wait_for(state=state, timeout=ctx.timeout_ms())


@register_action("wait_for_text", required=("selector", "value"), group="navigation",
                 description="Wait until the selector's text contains value.")
def wait_for_text(ctx: StepContext) -> dict:
    needle = ctx.field("value", required=True)
    loc = ctx.locator()
    ok = poll_until(lambda: needle in (loc.inner_text() or ""), ctx.timeout_ms())
    return {"pass": ok, "reason": None if ok else f"text {needle!r} not found within timeout"}


@register_action("wait_for_url", required=("value",), group="navigation",
                 description="Wait until the current URL contains value.")
def wait_for_url(ctx: StepContext) -> dict:
    needle = ctx.field("value", required=True)
    ok = poll_until(lambda: needle in ctx.page.url, ctx.timeout_ms())
    return {"pass": ok, "reason": None if ok else f"url never contained {needle!r}"}


@register_action("wait_for_load_state", group="navigation",
                 description="Wait for load state: load | domcontentloaded | networkidle.")
def wait_for_load_state(ctx: StepContext) -> None:
    ctx.page.wait_for_load_state(ctx.step.get("state", "load"), timeout=ctx.timeout_ms())
