"""Phoenix LiveView extension.

Opt in with ``extensions = ["liveview"]``. Adds:

  * ``wait_for_lv``  — wait until LiveView has settled (socket connected, no pending
    events, no in-flight ``phx-*-loading`` / ``data-phx-ref-src`` elements).
  * ``phx_push``     — push a LiveView event straight over the joined ``lv:`` channel,
    bypassing the UI (use sparingly).
  * an ``after_step`` hook that auto-settles LiveView after interaction steps, so most
    flows don't need explicit ``wait_for_lv`` calls.
  * :func:`wait_for_join` / :func:`push_event` — Python helpers for app reset hooks
    (``@reset_hook``) that must push an event once the LiveView channel has joined.
    The join wait is budgeted by config ``reset_join_timeout_ms`` and retried
    ``reset_join_attempts`` times (reloading between attempts), because a single-shot
    wait races the join right after a server code reload.

Keeping this out of the core ``submit``/``click`` actions is what lets the engine stay
framework-agnostic.
"""

from __future__ import annotations

import time
from typing import Any

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


# JS predicate: true once at least one lv: channel has joined.
_JOINED_JS = """() => {
  const ls = window.liveSocket;
  if (!ls || !ls.getSocket) return false;
  return (ls.getSocket().channels || []).some(
    c => c.state === 'joined' && (c.topic || '').startsWith('lv:'));
}"""


def wait_for_join(ctx: StepContext, *, timeout_ms: int | None = None,
                  attempts: int | None = None, reload: bool = True) -> bool:
    """Wait until a LiveView ``lv:`` channel has joined; return True when it has.

    Meant for ``@reset_hook``s that push a reset event (the page must already be on a
    LiveView route). The total budget (default config ``reset_join_timeout_ms``) is
    split over ``attempts`` tries (default config ``reset_join_attempts``); between
    tries the page is reloaded (when *reload*), which recovers a socket stuck in
    rejoin backoff after a server code reload. Errors such as a navigation destroying
    the execution context count as a failed try, never an exception.
    """
    budget = int(timeout_ms if timeout_ms is not None else ctx.config.reset_join_timeout_ms)
    tries = max(1, int(attempts if attempts is not None else ctx.config.reset_join_attempts))
    per_try = max(1, budget // tries)
    for attempt in range(1, tries + 1):
        started = time.monotonic()
        try:
            ctx.page.wait_for_function(_JOINED_JS, timeout=per_try)
            return True
        except Exception as exc:  # noqa: BLE001 - timeout / context destroyed by a reload
            ctx.log.wat(f"liveview join not ready (attempt {attempt}/{tries}, "
                        f"{int((time.monotonic() - started) * 1000)}ms): {exc}", level="warn")
        if reload and attempt < tries:
            try:
                ctx.page.reload()
            except Exception:  # noqa: BLE001 - the next wait reports the real state
                pass
    return False


def push_event(ctx: StepContext, event: str, payload: dict[str, Any] | None = None) -> dict:
    """Push *event* over every joined ``lv:`` channel; returns ``{"ok": bool, ...}``."""
    result = ctx.page.evaluate(_PUSH_JS, [event, payload or {}])
    return result if isinstance(result, dict) else {"ok": False, "reason": "push failed"}


@register_action("wait_for_lv", group="liveview",
                 description="Wait until Phoenix LiveView has settled (no pending events).")
def wait_for_lv(ctx: StepContext) -> None:
    ctx.page.wait_for_function(_SETTLED_JS, timeout=ctx.timeout_ms())


@register_action("phx_push", required=("event",), group="liveview",
                 description="Push a LiveView event over the joined lv: channel.")
def phx_push(ctx: StepContext) -> dict:
    event = ctx.field("event", required=True)
    payload = ctx.step.get("payload", {})
    result = push_event(ctx, event, payload)
    ok = bool(result.get("ok"))
    if ok:
        _settle_quietly(ctx)
    return {"pass": ok, "reason": None if ok else result.get("reason", "push failed")}


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
