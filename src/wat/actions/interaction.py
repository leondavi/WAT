"""Interaction actions: clicking, typing, forms, drag-and-drop, uploads.

All locators auto-wait for actionability (visible, enabled, stable) before acting,
which removes most of the explicit waits the Selenium forks needed.
"""

from __future__ import annotations

from pathlib import Path

from ..context import StepContext
from ..registry import register_action

_SUBMIT_JS = (
    "el => { const f = el.tagName === 'FORM' ? el : (el.form || el.closest('form')); "
    "if (!f) throw new Error('no form for submit'); "
    "if (f.requestSubmit) f.requestSubmit(); else f.submit(); }"
)


@register_action("click", required=("selector",), group="interaction",
                 description="Click the first matching element.")
def click(ctx: StepContext) -> None:
    ctx.locator().click(timeout=ctx.timeout_ms())


@register_action("dblclick", required=("selector",), group="interaction",
                 description="Double-click the element.")
def dblclick(ctx: StepContext) -> None:
    ctx.locator().dblclick(timeout=ctx.timeout_ms())


@register_action("hover", required=("selector",), group="interaction", description="Hover the element.")
def hover(ctx: StepContext) -> None:
    ctx.locator().hover(timeout=ctx.timeout_ms())


@register_action("right_click", required=("selector",), group="interaction",
                 description="Right-click (context menu) the element.")
def right_click(ctx: StepContext) -> None:
    ctx.locator().click(button="right", timeout=ctx.timeout_ms())


@register_action("type", aliases=("fill",), required=("selector", "value"), group="interaction",
                 description="Fill an input with value (fires input events; LiveView-friendly).")
def type_(ctx: StepContext) -> None:
    loc = ctx.locator()
    value = str(ctx.field("value", required=True))
    if ctx.step.get("append"):
        loc.press_sequentially(value, timeout=ctx.timeout_ms())
    else:
        loc.fill(value, timeout=ctx.timeout_ms())


@register_action("press", required=("selector",), group="interaction",
                 description="Press a key or chord (e.g. 'Enter', 'Control+A') on the element.")
def press(ctx: StepContext) -> None:
    keys = ctx.field("keys") or ctx.field("value")
    ctx.locator().press(str(keys), timeout=ctx.timeout_ms())


@register_action("clear", required=("selector",), group="interaction", description="Clear an input.")
def clear(ctx: StepContext) -> None:
    ctx.locator().fill("", timeout=ctx.timeout_ms())


@register_action("submit", required=("selector",), group="interaction",
                 description="Submit the form containing the selector.")
def submit(ctx: StepContext) -> None:
    ctx.locator().evaluate(_SUBMIT_JS)


@register_action("check", required=("selector",), group="interaction", description="Check a checkbox/radio.")
def check(ctx: StepContext) -> None:
    ctx.locator().check(timeout=ctx.timeout_ms())


@register_action("uncheck", required=("selector",), group="interaction", description="Uncheck a checkbox.")
def uncheck(ctx: StepContext) -> None:
    ctx.locator().uncheck(timeout=ctx.timeout_ms())


@register_action("select_option", required=("selector",), group="interaction",
                 description="Choose a <select> option by value or label.")
def select_option(ctx: StepContext) -> None:
    loc = ctx.locator()
    if "label" in ctx.step:
        loc.select_option(label=str(ctx.field("label")), timeout=ctx.timeout_ms())
    else:
        loc.select_option(value=str(ctx.field("value", required=True)), timeout=ctx.timeout_ms())


@register_action("set_file", aliases=("upload",), required=("selector",), group="interaction",
                 description="Upload file(s) to a file input; paths are repo-relative.")
def set_file(ctx: StepContext) -> None:
    raw = ctx.field("path") or ctx.field("value")
    paths = raw if isinstance(raw, list) else [raw]
    resolved = [str(_resolve_path(ctx, p)) for p in paths]
    ctx.locator().set_input_files(resolved, timeout=ctx.timeout_ms())


@register_action("focus", required=("selector",), group="interaction", description="Focus the element.")
def focus(ctx: StepContext) -> None:
    ctx.locator().focus(timeout=ctx.timeout_ms())


@register_action("blur", required=("selector",), group="interaction", description="Blur the element.")
def blur(ctx: StepContext) -> None:
    ctx.locator().evaluate("el => el.blur()")


@register_action("real_drag", aliases=("drag_and_drop",),
                 required=("from_selector", "to_selector"), group="interaction",
                 description="Mouse-driven drag from one element to another.")
def real_drag(ctx: StepContext) -> None:
    source = ctx.locator({"by": ctx.step.get("from_by", "css"),
                          "selector": ctx.field("from_selector", required=True)})
    target = ctx.locator({"by": ctx.step.get("to_by", "css"),
                          "selector": ctx.field("to_selector", required=True)})
    source.drag_to(target, timeout=ctx.timeout_ms())


def _resolve_path(ctx: StepContext, p: str) -> Path:
    path = Path(str(p))
    return path if path.is_absolute() else (Path(ctx.config.root) / path)
