"""Session reuse: the save_storage_state action + per-flow storage_state override."""

from __future__ import annotations

import json

import pytest

import wat  # noqa: F401 — registers core actions
from wat.actions import browser as B
from wat.config import WatConfig
from wat.errors import StepFailure
from wat.runner import _flow_config
from conftest import FakeContext, make_ctx


def test_save_storage_state_writes_to_resolved_path(tmp_path):
    ctx = make_ctx({"action": "save_storage_state", "path": "auth/admin.json"},
                   config=WatConfig(root=str(tmp_path)), browser_context=FakeContext())
    B.save_storage_state(ctx)
    written = tmp_path / "auth" / "admin.json"
    assert ctx.browser_context.saved_to == str(written)  # parent dir was created + passed to Playwright


def test_save_storage_state_falls_back_to_config_path(tmp_path):
    cfg = WatConfig(root=str(tmp_path), storage_state="state.json")
    ctx = make_ctx({"action": "save_storage_state"}, config=cfg, browser_context=FakeContext())
    B.save_storage_state(ctx)
    assert ctx.browser_context.saved_to == str(tmp_path / "state.json")


def test_save_storage_state_needs_a_path():
    ctx = make_ctx({"action": "save_storage_state"}, browser_context=FakeContext())
    with pytest.raises(StepFailure):
        B.save_storage_state(ctx)


def test_flow_config_applies_per_flow_override():
    base = WatConfig(storage_state="global.json")
    # A flow can pin its own state...
    assert _flow_config(base, {"storage_state": "flow.json"}).storage_state == "flow.json"
    # ...clear it (force a fresh context)...
    assert _flow_config(base, {"storage_state": ""}).storage_state is None
    # ...or leave it untouched (same object returned).
    assert _flow_config(base, {}) is base
