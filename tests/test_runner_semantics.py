"""Runner pass/fail semantics: retry / optional / soft on native (Playwright-style)
errors, ``if`` predicate failures, ``after_flow`` hooks, and ``--all`` robustness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import wat  # noqa: F401 — registers core actions
from wat import runner as R
from wat.actions.assertions import assert_attribute
from wat.config import WatConfig
from wat.errors import AssertionFailure, StepFailure
from wat.registry import Registry
from conftest import FakeLocator, FakePage, make_ctx


class TimeoutError(Exception):  # noqa: A001 — mimics playwright's sync_api.TimeoutError name
    pass


def _flaky_registry(fail_times: int) -> tuple[Registry, list[int]]:
    """A registry whose ``flaky`` action raises a native timeout *fail_times* times."""
    reg = Registry()
    calls: list[int] = []

    @reg.action("flaky")
    def flaky(ctx):
        calls.append(1)
        if len(calls) <= fail_times:
            raise TimeoutError("Locator.click: Timeout 200ms exceeded")

    return reg, calls


def test_retry_applies_to_native_errors(monkeypatch):
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    reg, calls = _flaky_registry(fail_times=2)
    R._run_step(make_ctx({"action": "flaky", "retry": 2}), 0, reg, [])
    assert len(calls) == 3


def test_optional_absorbs_native_errors():
    reg, _ = _flaky_registry(fail_times=99)
    R._run_step(make_ctx({"action": "flaky", "optional": True}), 0, reg, [])  # no raise


def test_soft_records_native_errors_and_continues():
    reg, _ = _flaky_registry(fail_times=99)
    soft: list[str] = []
    R._run_step(make_ctx({"action": "flaky", "soft": True}), 0, reg, soft)
    assert len(soft) == 1 and "Timeout" in soft[0]


def test_hard_native_failure_is_classified_browser():
    reg, _ = _flaky_registry(fail_times=99)
    with pytest.raises(AssertionFailure) as info:
        R._run_step(make_ctx({"action": "flaky"}), 0, reg, [])
    assert info.value.source == "browser"


def test_broken_if_predicate_fails_instead_of_skipping():
    class BoomPage(FakePage):
        def evaluate(self, expr, arg=None):
            raise RuntimeError("ReferenceError: lenght is not defined")

    reg, calls = _flaky_registry(fail_times=0)
    ctx = make_ctx({"action": "flaky", "if": "document.body.lenght > 0"}, page=BoomPage())
    with pytest.raises(StepFailure) as info:
        R._run_step(ctx, 0, reg, [])
    assert info.value.source == "flow_authoring"
    assert calls == []


@pytest.mark.parametrize("value", [None, 0, ""])
def test_dict_pass_must_be_truthy(value):
    assert R._interpret({"pass": value}, None)[0] is False


def test_after_flow_hooks_run_and_never_raise():
    reg = Registry()
    seen: list[str] = []

    @reg.hook("after_flow")
    def teardown(ctx):
        seen.append("ran")
        raise RuntimeError("cleanup failed")

    ctx = make_ctx({})
    R._run_after_flow(reg, ctx, ctx.log)
    assert seen == ["ran"]


def test_assert_attribute_without_value_requires_presence():
    page = FakePage(locators={"#b": FakeLocator(attrs={})})
    assert assert_attribute(make_ctx({"selector": "#b", "attr": "disabled"}, page=page))["pass"] is False
    page = FakePage(locators={"#b": FakeLocator(attrs={"disabled": ""})})
    assert assert_attribute(make_ctx({"selector": "#b", "attr": "disabled"}, page=page))["pass"] is True


def test_secret_values_are_masked_in_live_step_log():
    desc = R._describe({"action": "type", "selector": "#password", "value": "hunter2"})
    assert "hunter2" not in desc and "<masked>" in desc
    assert "hello" in R._describe({"action": "type", "selector": "#q", "value": "hello"})


def _write_flows(tmp_path: Path) -> list[Path]:
    good = tmp_path / "fl_a_good.json"
    good.write_text(json.dumps({"steps": [{"action": "reload"}]}))
    bad = tmp_path / "fl_b_bad.json"
    bad.write_text(json.dumps({"steps": []}))
    return [good, bad]


def test_malformed_flow_becomes_a_failed_result(tmp_path, monkeypatch):
    class _Session:
        def __init__(self, *a, **k): pass
        def start(self): return self
        def close(self): pass

    monkeypatch.setattr(R, "BrowserSession", _Session)
    monkeypatch.setattr(R, "execute_flow", lambda path, *a, **k: R.FlowResult(
        path=path, name=path.stem, returncode=0, status="pass", duration_ms=1))
    results = R.run_flows(_write_flows(tmp_path), WatConfig())
    assert [r.status for r in results] == ["pass", "fail"]
    assert results[1].source == "flow_authoring"


def test_parallel_fail_fast_starts_no_new_flows(tmp_path, monkeypatch):
    paths = []
    for i in range(6):
        p = tmp_path / f"fl_{i}.json"
        p.write_text(json.dumps({"steps": [{"action": "reload"}]}))
        paths.append(p)
    monkeypatch.setattr(R, "execute_flow", lambda path, *a, **k: R.FlowResult(
        path=path, name=path.stem, returncode=1, status="fail", duration_ms=1))
    results = R.run_flows(paths, WatConfig(workers=2, fail_fast=True))
    assert 1 <= len(results) < len(paths)
