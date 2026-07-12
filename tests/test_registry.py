"""Registry: registration, override, aliases, hook ordering, dispatch errors."""

from __future__ import annotations

import pytest

from wat.errors import ActionAlreadyRegistered, ActionNotFound
from wat.registry import Registry


def test_register_and_get():
    reg = Registry()

    @reg.action("noop", required=("x",), description="does nothing")
    def _noop(ctx):
        return True

    meta = reg.get("noop")
    assert meta.handler is _noop
    assert meta.required == ("x",)
    assert reg.has("noop")


def test_aliases_resolve_to_same_handler():
    reg = Registry()

    @reg.action("primary", aliases=("alt",))
    def _h(ctx):
        return None

    assert reg.get("alt").handler is reg.get("primary").handler
    # aliases are excluded from the canonical name list
    assert reg.names() == ["primary"]


def test_duplicate_without_override_raises():
    reg = Registry()
    reg.action("dup")(lambda ctx: None)
    with pytest.raises(ActionAlreadyRegistered):
        reg.action("dup")(lambda ctx: None)


def test_override_replaces_handler():
    reg = Registry()
    reg.action("dup")(lambda ctx: "first")

    @reg.action("dup", override=True)
    def _second(ctx):
        return "second"

    assert reg.get("dup").handler is _second


def test_unknown_action_raises_action_not_found():
    with pytest.raises(ActionNotFound):
        Registry().get("does_not_exist")


def test_hooks_preserve_registration_order():
    reg = Registry()
    order: list[str] = []
    reg.hook("before_step")(lambda ctx: order.append("a"))
    reg.hook("before_step")(lambda ctx: order.append("b"))
    for h in reg.hooks("before_step"):
        h(None)
    assert order == ["a", "b"]


def test_invalid_hook_phase_rejected():
    with pytest.raises(ValueError):
        Registry().hook("nonsense")


def test_login_provider_and_reset_registration():
    reg = Registry()
    reg.login_provider(lambda ctx: None)
    reg.reset(lambda ctx: None)
    assert reg.get_login_provider() is not None
    assert reg.get_reset_hook() is not None
