"""Browser & session actions: cookies, storage, viewport, dialogs, emulation.

These give flows control over the ambient browser state that complex journeys often
depend on (a seeded cookie, a cleared localStorage, a mobile viewport, an accepted
``confirm()`` dialog) without dropping to raw ``eval_js``.
"""

from __future__ import annotations

from ..context import StepContext
from ..registry import register_action


# -- cookies -----------------------------------------------------------------

@register_action("set_cookie", required=("name", "value"), group="browser",
                 description="Add a cookie scoped to the base URL.")
def set_cookie(ctx: StepContext) -> None:
    ctx.browser_context.add_cookies([{
        "name": str(ctx.field("name", required=True)),
        "value": str(ctx.field("value", required=True)),
        "url": ctx.base_url,
    }])


@register_action("clear_cookies", group="browser", description="Clear all cookies.")
def clear_cookies(ctx: StepContext) -> None:
    ctx.browser_context.clear_cookies()


# -- web storage -------------------------------------------------------------

@register_action("set_storage", required=("name", "value"), group="browser",
                 description="Set a local/session storage key (area defaults to local).")
def set_storage(ctx: StepContext) -> None:
    area = ctx.step.get("area", "local")
    name = str(ctx.field("name", required=True))
    value = str(ctx.field("value", required=True))
    ctx.page.evaluate(f"([k,v]) => window.{area}Storage.setItem(k, v)", [name, value])


@register_action("get_storage", required=("name",), group="browser",
                 description="Read a storage key into the capture store (needs store_as).")
def get_storage(ctx: StepContext) -> None:
    area = ctx.step.get("area", "local")
    name = str(ctx.field("name", required=True))
    val = ctx.page.evaluate(f"(k) => window.{area}Storage.getItem(k)", name)
    if ctx.step.get("store_as"):
        ctx.store[ctx.step["store_as"]] = val


@register_action("clear_storage", group="browser", description="Clear local + session storage.")
def clear_storage(ctx: StepContext) -> None:
    ctx.page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")


# -- viewport & emulation ----------------------------------------------------

@register_action("set_viewport", required=("width", "height"), group="browser",
                 description="Resize the viewport.")
def set_viewport(ctx: StepContext) -> None:
    ctx.page.set_viewport_size({
        "width": int(ctx.field("width", required=True)),
        "height": int(ctx.field("height", required=True)),
    })


@register_action("emulate", group="browser",
                 description="Emulate offline / geolocation / color-scheme / media.")
def emulate(ctx: StepContext) -> None:
    step = ctx.step
    if "offline" in step:
        ctx.browser_context.set_offline(bool(step["offline"]))
    if "geolocation" in step:
        geo = step["geolocation"]
        ctx.browser_context.set_geolocation({"latitude": geo["lat"], "longitude": geo["lon"]})
    if "color_scheme" in step:
        ctx.page.emulate_media(color_scheme=str(step["color_scheme"]))


# -- dialogs -----------------------------------------------------------------

@register_action("handle_dialog", group="browser",
                 description="Auto-handle the next dialog: accept | dismiss (with optional prompt text).")
def handle_dialog(ctx: StepContext) -> None:
    action = ctx.step.get("dialog", "accept")
    prompt_text = ctx.field("value")

    def _handler(dialog):
        ctx.log.browser(f"dialog '{dialog.type}': {dialog.message}")
        if action == "dismiss":
            dialog.dismiss()
        else:
            dialog.accept(prompt_text) if prompt_text is not None else dialog.accept()

    # once=True so it only affects the next dialog.
    ctx.page.once("dialog", _handler)
