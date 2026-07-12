"""Phoenix LiveView extension.

Opt in with ``extensions = ["liveview"]``. Adds:

  * ``wait_for_lv``  — wait until LiveView has settled (socket connected, no pending
    events, no in-flight ``phx-*-loading`` / ``data-phx-ref-src`` elements).
  * ``phx_push``     — push a LiveView event straight over the joined ``lv:`` channel,
    bypassing the UI (use sparingly).
  * an ``after_step`` hook that auto-settles LiveView after interaction steps, so most
    flows don't need explicit ``wait_for_lv`` calls.

Keeping this out of the core ``submit``/``click`` actions is what lets the engine stay
framework-agnostic.
"""

from __future__ import annotations

from ..context import StepContext
from ..registry import register_action, register_hook

# Interaction actions after which LiveView may re-render; we settle after these.
_INTERACTIONS = {"click", "type", "fill", "submit", "select_option", "check", "uncheck", "press"}

# JS predicate: true once LiveView is connected and nothing is pending.
_SETTLED_JS = """() => {
  const ls = window.liveSocket;
  if (!ls || !ls.isConnected || !ls.isConnected()) return false;
  if (document.querySelector('[data-phx-ref-src], .phx-change-loading, .phx-click-loading, .phx-submit-loading')) return false;
  return !(ls.hasPendingLink && ls.hasPendingLink());
}"""

# JS to push an event over every joined lv: channel (mirrors the app's own wire path).
_PUSH_JS = """([event, payload]) => {
  if (!window.liveSocket) return {ok: false, reason: 'no liveSocket'};
  const socket = window.liveSocket.getSocket();
  const chans = (socket.channels || []).filter(c => c.state === 'joined' && (c.topic || '').startsWith('lv:'));
  if (!chans.length) return {ok: false, reason: 'no joined lv: channel'};
  chans.forEach(ch => ch.push('event', {type: 'click', event: event, value: payload || {}}));
  return {ok: true, channels: chans.length};
}"""


@register_action("wait_for_lv", group="liveview",
                 description="Wait until Phoenix LiveView has settled (no pending events).")
def wait_for_lv(ctx: StepContext) -> None:
    ctx.page.wait_for_function(_SETTLED_JS, timeout=ctx.timeout_ms())


@register_action("phx_push", required=("event",), group="liveview",
                 description="Push a LiveView event over the joined lv: channel.")
def phx_push(ctx: StepContext) -> dict:
    event = ctx.field("event", required=True)
    payload = ctx.step.get("payload", {})
    result = ctx.page.evaluate(_PUSH_JS, [event, payload])
    ok = bool(result and result.get("ok"))
    if ok:
        _settle_quietly(ctx)
    return {"pass": ok, "reason": None if ok else (result or {}).get("reason", "push failed")}


@register_hook("after_step")
def _settle_after_interaction(ctx: StepContext) -> None:
    """Best-effort LiveView settle after any interaction step."""
    if ctx.step.get("action") in _INTERACTIONS and not ctx.step.get("no_lv_settle"):
        _settle_quietly(ctx)


def _settle_quietly(ctx: StepContext) -> None:
    try:
        ctx.page.wait_for_function(_SETTLED_JS, timeout=min(ctx.timeout_ms(), 5000))
    except Exception:
        # Settling is an optimization; never fail a step because it didn't settle.
        pass
