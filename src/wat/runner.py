"""The flow runner: dispatch, lifecycle hooks, retries, and soft assertions.

``run_flow`` drives a single flow end-to-end and returns an exit code (0 pass,
1 fail). ``run_step`` executes one step through the registry, honoring the per-step
robustness keys (``timeout``, ``retry``, ``optional``, ``if``/``skip_if``, ``soft``)
that let flows absorb flakiness declaratively instead of with ad-hoc sleeps.
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from .config import WatConfig
from .context import StepContext
from .driver import Driver
from .errors import AssertionFailure, StepFailure, SOURCE_APP, SOURCE_BROWSER
from .logging import RunLogger
from .registry import REGISTRY, Registry
from .reporting import write_failure_artifacts, write_success_summary
from .schema import load_flow


def run_flow(flow_path: str | Path, config: WatConfig, registry: Registry = REGISTRY) -> int:
    """Run one flow file. Returns 0 on success, 1 on failure."""
    flow_path = Path(flow_path)
    flow = load_flow(flow_path)
    flow["__path__"] = str(flow_path)
    stem = flow_path.stem

    soft_failures: list[str] = []
    with RunLogger(app=config.app_name, log_dir=config.log_dir, flow_stem=stem,
                   level=config.log_level, keep_runs=config.keep_runs) as log:
        log.wat(f"flow '{flow.get('name', stem)}' — {len(flow['steps'])} steps @ {config.base_url}")
        driver = Driver(config, log)
        failed_index: int | None = None
        failed_action: str | None = None
        try:
            driver.start()
            ctx = StepContext(page=driver.page, browser_context=driver.context, driver=driver,
                              config=config, flow=flow, flow_stem=stem, log=log)

            for hook in registry.hooks("before_flow"):
                hook(ctx)
            reset = registry.get_reset_hook()
            if reset is not None:
                _safe_hook(reset, ctx, log, "reset")

            for index, step in enumerate(flow["steps"]):
                step_ctx = replace(ctx, step=step)
                failed_index, failed_action = index, step.get("action")
                _run_step(step_ctx, index, registry, soft_failures)

            _final_checks(driver, config, soft_failures)
            if soft_failures:
                raise AssertionFailure(
                    f"{len(soft_failures)} soft assertion(s) failed:\n  - "
                    + "\n  - ".join(soft_failures),
                    source=SOURCE_APP,
                )

            driver.drain_diagnostics()
            write_success_summary(ctx=ctx, log=log, steps_run=len(flow["steps"]))
            log.wat(f"PASSED ({len(flow['steps'])} steps)")
            driver.stop(save_trace=False)
            return 0

        except BaseException as exc:  # noqa: BLE001 — we classify and report every failure
            driver.drain_diagnostics()
            write_failure_artifacts(ctx=_ctx_for_report(driver, config, flow, stem, log),
                                    driver=driver, log=log, exc=exc,
                                    failed_index=failed_index, failed_action=failed_action)
            log.wat(f"FAILED at step {failed_index} ({failed_action}): {exc}", level="error")
            _maybe_pause_on_failure(driver, config, log)
            driver.stop(save_trace=True, trace_path=log.dir / "trace.zip")
            return 1


# ---------------------------------------------------------------------------
# Step execution
# ---------------------------------------------------------------------------

def _run_step(ctx: StepContext, index: int, registry: Registry, soft_failures: list[str]) -> None:
    step = ctx.step
    action = step.get("action")
    started = time.monotonic()

    if _should_skip(ctx):
        ctx.log.step({"index": index, "action": action, "status": "skipped", "duration_ms": 0})
        return

    # In a live run, announce each step's intent BEFORE it runs so a watcher can
    # correlate what they see in the headed browser with the log.
    if ctx.config.verbose_steps_effective():
        ctx.log.wat(f"→ [{index}] {action} {_describe(step)}".rstrip())

    for hook in registry.hooks("before_step"):
        hook(ctx)

    attempts = int(step.get("retry", ctx.config.step_retries)) + 1
    last_error: BaseException | None = None
    result: Any = None
    for attempt in range(attempts):
        try:
            result = _dispatch(ctx, action, registry)
            last_error = None
            break
        except (StepFailure, AssertionError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                ctx.log.wat(f"step {index} ({action}) retry {attempt + 1}/{attempts - 1}: {exc}",
                            level="warn")
                time.sleep(min(0.5 * (attempt + 1), 2.0))

    duration_ms = int((time.monotonic() - started) * 1000)
    passed, reason = _interpret(result, last_error)

    if passed:
        ctx.log.step({"index": index, "action": action, "status": "ok",
                      "duration_ms": duration_ms, "selector": step.get("selector")})
    else:
        _handle_failure(ctx, index, action, reason, last_error, duration_ms, soft_failures)

    for hook in registry.hooks("after_step"):
        hook(ctx)


def _dispatch(ctx: StepContext, action: str, registry: Registry) -> Any:
    """Route to the login provider for ``login``, else the registered action handler."""
    if action == "login" and registry.get_login_provider() is not None:
        return registry.get_login_provider()(ctx)  # type: ignore[misc]
    return registry.get(action).handler(ctx)


def _interpret(result: Any, error: BaseException | None) -> tuple[bool, str | None]:
    """Reduce a handler result (+ any raised error) to (passed, reason)."""
    if error is not None:
        return False, getattr(error, "reason", None) or str(error)
    if result is None or result is True:
        return True, None
    if result is False:
        return False, None
    if isinstance(result, dict):
        verdict = result.get("pass", True)
        # pass: null == skip == treated as pass.
        return (verdict is not False), result.get("reason")
    return True, None


def _handle_failure(ctx: StepContext, index: int, action: str, reason: str | None,
                    error: BaseException | None, duration_ms: int, soft_failures: list[str]) -> None:
    step = ctx.step
    label = f"step {index} ({action})" + (f": {reason}" if reason else "")

    if step.get("optional"):
        ctx.log.step({"index": index, "action": action, "status": "optional-fail",
                      "duration_ms": duration_ms, "error": reason})
        ctx.log.wat(f"optional {label} failed — continuing", level="warn")
        return

    soft = step.get("soft", ctx.config.soft_asserts and str(action).startswith("assert"))
    if soft:
        soft_failures.append(label)
        ctx.log.step({"index": index, "action": action, "status": "soft-fail",
                      "duration_ms": duration_ms, "error": reason})
        return

    ctx.log.step({"index": index, "action": action, "status": "fail",
                  "duration_ms": duration_ms, "error": reason})
    if isinstance(error, StepFailure):
        raise error
    raise AssertionFailure(label, source=getattr(error, "source", SOURCE_APP),
                           step_index=index, action=action, reason=reason)


def _should_skip(ctx: StepContext) -> bool:
    """Evaluate optional ``if`` / ``skip_if`` JS predicates gating this step."""
    step = ctx.step
    if "if" in step and not _truthy_js(ctx, step["if"]):
        return True
    if "skip_if" in step and _truthy_js(ctx, step["skip_if"]):
        return True
    return False


def _truthy_js(ctx: StepContext, expr: str) -> bool:
    try:
        return bool(ctx.page.evaluate(f"() => ({ctx.resolve(expr)})"))
    except Exception:
        return False


def _final_checks(driver: Driver, config: WatConfig, soft_failures: list[str]) -> None:
    """Optionally fail the flow if the page raised an uncaught JS exception."""
    if config.fail_on_pageerror and driver.page_errors:
        raise StepFailure(
            f"uncaught page error(s): {driver.page_errors[0]}",
            source=SOURCE_BROWSER,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx_for_report(driver: Driver, config: WatConfig, flow: dict, stem: str, log: RunLogger) -> StepContext:
    return StepContext(page=driver.page, browser_context=driver.context, driver=driver,
                       config=config, flow=flow, flow_stem=stem, log=log)


def _safe_hook(hook: Any, ctx: StepContext, log: RunLogger, name: str) -> None:
    try:
        hook(ctx)
    except Exception as exc:  # a flaky reset must never mask real assertions
        log.wat(f"{name} hook failed (ignored): {exc}", level="warn")


def _describe(step: dict) -> str:
    """A short 'what this step targets' string for live per-step logging."""
    parts = []
    if step.get("selector"):
        by = step.get("by", "css")
        parts.append(f"{by}={step['selector']!r}")
    for key in ("url", "value", "event", "pattern", "count", "seconds"):
        if key in step:
            val = str(step[key])
            parts.append(f"{key}={val[:60]!r}" if key == "value" else f"{key}={val}")
    return " ".join(parts)


def _maybe_pause_on_failure(driver: Driver, config: WatConfig, log: RunLogger) -> None:
    """In a headed run with pause_on_failure, hold the browser open (Playwright
    Inspector) so the failure can be inspected live. No-op when headless."""
    if not config.pause_on_failure or config.headless:
        return
    try:
        log.wat("pausing on failure — resume in the Playwright Inspector to continue", level="warn")
        driver.page.pause()
    except Exception:
        pass
