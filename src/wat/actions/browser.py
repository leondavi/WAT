"""Browser & session actions: cookies, storage, viewport, dialogs, emulation.

These give flows control over the ambient browser state that complex journeys often
depend on (a seeded cookie, a cleared localStorage, a mobile viewport, an accepted
``confirm()`` dialog) without dropping to raw ``eval_js``.
"""

from __future__ import annotations

from pathlib import Path

from ..context import StepContext
from ..errors import StepFailure, SOURCE_FLOW_AUTHORING
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


# -- session reuse -----------------------------------------------------------

@register_action("save_storage_state", aliases=("save_auth",), group="browser",
                 description="Persist cookies + localStorage to a file for reuse via config.storage_state.")
def save_storage_state(ctx: StepContext) -> None:
    """Save the context's cookies + localStorage so later runs can skip logging in.

    Typically the last step of a dedicated setup flow; point other flows at the same
    file via config ``storage_state`` (or a per-flow ``storage_state`` key)."""
    raw = ctx.field("path") or ctx.config.storage_state
    if not raw:
        raise StepFailure("save_storage_state needs 'path' or config.storage_state",
                          source=SOURCE_FLOW_AUTHORING)
    path = Path(str(raw))
    if not path.is_absolute():
        path = Path(ctx.config.root) / path
    path.parent.mkdir(parents=True, exist_ok=True)
    ctx.browser_context.storage_state(path=str(path))
    ctx.log.wat(f"saved storage state -> {path}")


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
