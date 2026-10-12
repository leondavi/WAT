"""Reset-hook outcomes (issue #8): skipped resets become warnings or failures, and the
LiveView join wait retries instead of a single-shot deadline.

Pure tests use the fake page; one end-to-end test drives ``execute_flow`` in real
Chromium (skipped automatically when it is unavailable).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wat.config import WatConfig
from wat.errors import StepFailure
from wat.ext import liveview as LV
from wat.registry import Registry
from wat.reports import build_html, build_json, build_junit
from wat.runner import FlowResult, _run_reset, execute_flow
from wat.schema import validate_flow
from conftest import FakePage, make_ctx


def _ctx(flow=None, **cfg):
    ctx = make_ctx({}, config=WatConfig(**cfg))
    ctx.flow = flow or {}
    return ctx


# ---------------------------------------------------------------------------
# _run_reset: hook outcome -> warning / failure
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("outcome", [None, True, {"pass": True}])
def test_successful_reset_records_nothing(outcome):
    ctx = _ctx()
    _run_reset(lambda c: outcome, ctx)
    assert ctx.warnings == []


def test_skipped_reset_becomes_a_warning_with_reason():
    ctx = _ctx()
    _run_reset(lambda c: {"pass": False, "reason": "no joined lv: channel"}, ctx)
    assert len(ctx.warnings) == 1
    assert "reset hook skipped: no joined lv: channel" in ctx.warnings[0]


def test_false_and_exceptions_are_skips_too():
    ctx = _ctx()
    _run_reset(lambda c: False, ctx)

    def boom(c):
        raise RuntimeError("socket closed")

    _run_reset(boom, ctx)
    assert "no reason given" in ctx.warnings[0]
    assert "RuntimeError: socket closed" in ctx.warnings[1]


def test_reset_required_on_flow_fails_fast():
    ctx = _ctx(flow={"reset_required": True})
    with pytest.raises(StepFailure) as exc:
        _run_reset(lambda c: False, ctx)
    assert exc.value.action == "reset" and "reset_required" in str(exc.value)
    assert ctx.warnings == []


def test_config_default_and_flow_override():
    with pytest.raises(StepFailure):
        _run_reset(lambda c: False, _ctx(reset_required=True))
    ctx = _ctx(flow={"reset_required": False}, reset_required=True)
    _run_reset(lambda c: False, ctx)  # the flow opts out: warning, not failure
    assert len(ctx.warnings) == 1


def test_warnings_are_shared_by_per_step_context_copies():
    from dataclasses import replace

    ctx = _ctx()
    replace(ctx, step={"action": "x"}).warn("from a step")
    assert ctx.warnings == ["from a step"]


def test_schema_rejects_non_bool_reset_required():
    flow = {"reset_required": "yes", "steps": [{"action": "open", "url": "/"}]}
    assert "'reset_required' must be true or false" in validate_flow(flow, Registry())


# ---------------------------------------------------------------------------
# wait_for_join: budgeted retries with reload in between
# ---------------------------------------------------------------------------

class JoinPage(FakePage):
    """wait_for_function fails ``failures`` times, then succeeds."""

    def __init__(self, failures: int):
        super().__init__()
        self.failures = failures
        self.timeouts: list[int] = []
        self.reloads = 0

    def wait_for_function(self, js, timeout=None):
        self.timeouts.append(timeout)
        if len(self.timeouts) <= self.failures:
            raise RuntimeError("Execution context was destroyed")

    def reload(self):
        self.reloads += 1


def test_wait_for_join_retries_then_succeeds():
    page = JoinPage(failures=2)
    ctx = make_ctx({}, page=page, config=WatConfig(reset_join_timeout_ms=9000, reset_join_attempts=3))
    assert LV.wait_for_join(ctx) is True
    assert page.timeouts == [3000, 3000, 3000]  # the budget is split across attempts
    assert page.reloads == 2


def test_wait_for_join_gives_up_after_all_attempts():
    page = JoinPage(failures=99)
    ctx = make_ctx({}, page=page, config=WatConfig())
    assert LV.wait_for_join(ctx, timeout_ms=1000, attempts=4, reload=False) is False
    assert len(page.timeouts) == 4 and page.reloads == 0


def test_push_event_normalizes_non_dict_result():
    ctx = make_ctx({}, page=FakePage(evaluate_result=None))
    assert LV.push_event(ctx, "x") == {"ok": False, "reason": "push failed"}


# ---------------------------------------------------------------------------
# Reports surface warnings
# ---------------------------------------------------------------------------

def _warned_result():
    return FlowResult(path=Path("fl_chat.json"), name="Chat", returncode=0, status="pass",
                      duration_ms=10, warnings=["reset hook skipped: no joined lv: channel"])


def test_reports_include_warnings():
    data = json.loads(build_json([_warned_result()]))
    assert data["warned"] == 1 and data["flows"][0]["warnings"]
    assert "WARNING: reset hook skipped" in build_junit([_warned_result()])
    assert "WARN</span>" in build_html([_warned_result()])


# ---------------------------------------------------------------------------
# End to end (real browser): run.json + FlowResult carry the warning
# ---------------------------------------------------------------------------

def _chromium_or_skip():
    playwright = pytest.importorskip("playwright.sync_api")
    try:
        pw = playwright.sync_playwright().start()
        pw.chromium.launch(headless=True).close()
        pw.stop()
    except Exception as exc:  # no browser binaries installed
        pytest.skip(f"chromium unavailable: {exc}")


def _write_flow(tmp_path, extra=None):
    flow = {"name": "reset demo", "steps": [{"action": "noop"}], **(extra or {})}
    path = tmp_path / "fl_reset_demo.json"
    path.write_text(json.dumps(flow), encoding="utf-8")
    return path


def _registry():
    reg = Registry()
    reg.action("noop")(lambda ctx: None)
    reg.reset(lambda ctx: {"pass": False, "reason": "no joined lv: channel"})
    return reg


def test_execute_flow_reports_skipped_reset(tmp_path):
    _chromium_or_skip()
    cfg = WatConfig(root=str(tmp_path), log_dir=str(tmp_path / "logs"), trace="off")
    result = execute_flow(_write_flow(tmp_path), cfg, _registry())
    assert result.returncode == 0 and len(result.warnings) == 1
    run = json.loads((result.log_dir / "run.json").read_text())
    assert run["result"] == "pass" and "reset hook skipped" in run["warnings"][0]


def test_execute_flow_fails_when_reset_required(tmp_path):
    _chromium_or_skip()
    cfg = WatConfig(root=str(tmp_path), log_dir=str(tmp_path / "logs"), trace="off")
    result = execute_flow(_write_flow(tmp_path, {"reset_required": True}), cfg, _registry())
    assert result.returncode == 1 and "reset_required" in (result.message or "")
