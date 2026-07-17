"""The flow runner: dispatch, lifecycle hooks, retries, and soft assertions.

``run_flow`` drives a single flow end-to-end and returns an exit code (0 pass,
1 fail). ``run_step`` executes one step through the registry, honoring the per-step
robustness keys (``timeout``, ``retry``, ``optional``, ``if``/``skip_if``, ``soft``)
that let flows absorb flakiness declaratively instead of with ad-hoc sleeps.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .config import WatConfig
from .context import StepContext
from .driver import BrowserSession, Driver
from .errors import AssertionFailure, StepFailure, SOURCE_APP, SOURCE_BROWSER
from .logging import ConsoleLog, RunLogger
from .registry import REGISTRY, Registry
from .reporting import write_failure_artifacts, write_success_summary
from .schema import flow_matrix, load_flow


@dataclass
class FlowResult:
    """Outcome of one flow run — the unit aggregated into summaries and reports."""

    path: Path
    name: str
    returncode: int          # 0 pass, 1 fail
    status: str              # "pass" | "fail"
    duration_ms: int
    source: str | None = None        # failure classification (app/browser/...)
    failed_step: int | None = None
    message: str | None = None
    log_dir: Path | None = None


def run_flow(flow_path: str | Path, config: WatConfig, registry: Registry = REGISTRY) -> int:
    """Run one flow file (expanding a ``matrix`` into a case per row). Returns 0 only if
    every case passed, else 1 (back-compat wrapper)."""
    results = run_flows([Path(flow_path)], config, registry)
    return 0 if all(r.returncode == 0 for r in results) else 1


def execute_flow(flow_path: str | Path, config: WatConfig, registry: Registry = REGISTRY,
                 session: BrowserSession | None = None, *, flow: dict[str, Any] | None = None,
                 initial_store: dict[str, Any] | None = None, stem_suffix: str = "",
                 case_label: str | None = None) -> FlowResult:
    """Run one flow (or one matrix case of it) and return a rich :class:`FlowResult`.

    If *session* is given, the flow runs in a fresh context on that shared browser
    (fast for ``--all``); otherwise a private browser is launched just for this flow.

    For a data-driven matrix case the caller passes the already-loaded *flow*, the row's
    *initial_store* (seeds ``{{var}}`` interpolation), a *stem_suffix* that keeps each
    case's log/artifact dir distinct, and a *case_label* appended to the result name.
    """
    flow_path = Path(flow_path)
    if flow is None:
        flow = load_flow(flow_path)
    flow["__path__"] = str(flow_path)
    stem = flow_path.stem
    log_stem = stem + stem_suffix
    name = flow.get("name", stem)
    if case_label:
        name = f"{name} [{case_label}]"
    started = time.monotonic()

    soft_failures: list[str] = []
    with RunLogger(app=config.app_name, log_dir=config.log_dir, flow_stem=log_stem,
                   level=config.log_level, keep_runs=config.keep_runs) as log:
        log.wat(f"flow '{name}' - {len(flow['steps'])} steps @ {config.base_url}")
        # A flow may pin its own storage_state (or clear it) without disturbing the rest
        # of the config; storage_state is a context kwarg, so this works on a shared
        # --all browser too (each flow still gets its own fresh context).
        driver = Driver(_flow_config(config, flow), log, session=session)
        failed_index: int | None = None
        failed_action: str | None = None
        summary: dict[str, Any] = {}
        rc = 0
        try:
            driver.start()
            ctx = StepContext(page=driver.page, browser_context=driver.context, driver=driver,
                              config=config, flow=flow, flow_stem=log_stem, log=log,
                              store=dict(initial_store or {}))

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
            summary = write_success_summary(ctx=ctx, log=log, steps_run=len(flow["steps"]))
            log.wat(f"PASSED ({len(flow['steps'])} steps)")
            driver.stop(save_trace=False)

        except BaseException as exc:  # noqa: BLE001 — we classify and report every failure
            rc = 1
            driver.drain_diagnostics()
            summary = write_failure_artifacts(ctx=_ctx_for_report(driver, config, flow, log_stem, log),
                                              driver=driver, log=log, exc=exc,
                                              failed_index=failed_index, failed_action=failed_action)
            log.wat(f"FAILED at step {failed_index} ({failed_action}): {exc}", level="error")
            _maybe_pause_on_failure(driver, config, log)
            driver.stop(save_trace=True, trace_path=log.dir / "trace.zip")

        return FlowResult(
            path=flow_path, name=name, returncode=rc,
            status="pass" if rc == 0 else "fail",
            duration_ms=int((time.monotonic() - started) * 1000),
            source=summary.get("source"), failed_step=summary.get("failed_step"),
            message=summary.get("error"), log_dir=log.dir,
        )


def run_flows(flow_paths: list[Path], config: WatConfig, registry: Registry = REGISTRY) -> list[FlowResult]:
    """Run many flows, honoring ``config.workers`` and ``config.fail_fast``.

    * workers == 1: one shared browser is reused across every flow (fast startup).
    * workers  > 1: flows run concurrently, each on its own browser (a Playwright
      sync session cannot cross threads), so throughput scales with cores.
    """
    if config.workers and config.workers > 1 and len(flow_paths) > 1:
        return _run_parallel(flow_paths, config, registry)
    return _run_sequential(flow_paths, config, registry)


def _run_sequential(flow_paths: list[Path], config: WatConfig, registry: Registry) -> list[FlowResult]:
    results: list[FlowResult] = []
    session = BrowserSession(config, ConsoleLog()).start()
    try:
        stop = False
        for path in flow_paths:
            for case in _load_cases(path):
                result = execute_flow(path, config, registry, session=session, **case)
                results.append(result)
                if config.fail_fast and result.returncode != 0:
                    stop = True
                    break
            if stop:
                break
    finally:
        session.close()
    return results


def _run_parallel(flow_paths: list[Path], config: WatConfig, registry: Registry) -> list[FlowResult]:
    # Each task launches its own browser (sessions are thread-bound). fail_fast in
    # parallel means "stop submitting more once one fails".
    tasks = [(path, case) for path in flow_paths for case in _load_cases(path)]
    results: list[FlowResult] = []
    with ThreadPoolExecutor(max_workers=config.workers) as pool:
        futures = [pool.submit(execute_flow, path, config, registry, **case) for path, case in tasks]
        for future in futures:  # preserves submission order
            results.append(future.result())
    return results


def _load_cases(flow_path: Path) -> list[dict[str, Any]]:
    """Load *flow_path* and expand its ``matrix`` into per-row execute_flow kwargs.

    A non-matrix flow yields exactly one case; a matrix of N rows yields N, each with a
    distinct ``stem_suffix`` (separate log/artifact dirs) and the row as ``initial_store``.
    The loaded flow dict is shared across a flow's cases (steps are read-only at run time).
    """
    flow = load_flow(flow_path)
    rows = flow_matrix(flow)
    if not rows:
        return [{"flow": flow, "initial_store": {}, "stem_suffix": "", "case_label": None}]
    return [{"flow": flow, "initial_store": row, "stem_suffix": f".case{i}",
             "case_label": ", ".join(f"{k}={v}" for k, v in row.items())}
            for i, row in enumerate(rows)]


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
    """Reduce a handler result (+ any raised error) to (passed, reason).

    On a dict failure, any diagnostic fields the handler attached beyond
    ``pass``/``reason`` (e.g. an ``assert_js`` script returning ``{pass:false,
    why:'...'}``) are serialized into the reason so they show up in the log.
    """
    if error is not None:
        return False, getattr(error, "reason", None) or str(error)
    if result is None or result is True:
        return True, None
    if result is False:
        return False, None
    if isinstance(result, dict):
        # pass: null == skip == treated as pass.
        passed = result.get("pass", True) is not False
        reason = result.get("reason")
        if not passed:
            extras = {k: v for k, v in result.items() if k not in ("pass", "reason")}
            if extras:
                blob = _truncate(_to_json(result))
                reason = f"{reason} | returned {blob}" if reason else f"returned {blob}"
        return passed, reason
    return True, None


def _to_json(obj: Any) -> str:
    import json

    try:
        return json.dumps(obj, default=str, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return repr(obj)


def _truncate(text: str, limit: int = 400) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


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

def _flow_config(config: WatConfig, flow: dict) -> WatConfig:
    """Apply a flow-level ``storage_state`` override (if any) to the config."""
    if "storage_state" not in flow:
        return config
    return replace(config, storage_state=flow.get("storage_state") or None)


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
