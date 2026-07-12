"""Failure artifacts, run summaries, and the fix-it agent prompt.

On failure the runner writes, into the per-run log dir:

    <flow>.failed.png    screenshot at the point of failure
    <flow>.failed.html   DOM snapshot
    <flow>.agent_prompt.txt   an LLM/human repro prompt, led by the failure *source*
    trace.zip            Playwright trace (saved by the driver)
    run.json             machine-readable summary (result, failed step, source, artifacts)

The ``source`` classification (wat_engine / browser / app / flow_authoring) is the
key to "is this WAT, the browser, or the app?".
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import SOURCE_APP, WatError


def git_branch(root: str | Path) -> str:
    """Best-effort current git branch of *root* (for the repro prompt)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(root), capture_output=True, text=True, check=False,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def classify(exc: BaseException) -> str:
    """Map an exception to a failure ``source`` label."""
    if isinstance(exc, WatError):
        return exc.source
    # Unknown/native exceptions (e.g. a Playwright timeout) are engine-level by default.
    name = type(exc).__name__
    if "Timeout" in name or "Playwright" in name:
        return "browser"
    return "wat_engine"


def build_agent_prompt(*, flow_path: Path, branch: str, source: str, error_text: str,
                       failed_index: int | None, failed_action: str | None,
                       reason: str | None, screenshot: Path, repro_command: str) -> str:
    """Compose the copy-paste repro prompt, leading with the failure source."""
    step = "unknown"
    if failed_index is not None:
        step = f"{failed_index}" + (f" ({failed_action})" if failed_action else "")
    repro = repro_command.format(flow=flow_path)
    lines = [
        "Investigate and fix a failing WAT (Playwright) flow.",
        "",
        f"Failure source: {source}   "
        "(wat_engine = framework, browser = page/console, app = app under test, "
        "flow_authoring = the flow file)",
        f"Branch: {branch}",
        f"Flow file: {flow_path}",
        f"Failed step: {step}",
        f"Error: {error_text}",
    ]
    if reason:
        lines.append(f"Assertion reason: {reason}")
    lines += [
        f"Failure screenshot: {screenshot}",
        "",
        "Please: (1) reproduce with the command below, (2) find the root cause at the",
        "layer named by 'Failure source', (3) apply a minimal fix, (4) re-run and report.",
        "",
        "Reproduction command:",
        repro,
    ]
    return "\n".join(lines)


def write_failure_artifacts(*, ctx: Any, driver: Any, log: Any, exc: BaseException,
                            failed_index: int | None, failed_action: str | None) -> dict[str, Any]:
    """Capture screenshot + DOM + agent prompt + run.json. Returns the summary dict."""
    out_dir: Path = log.dir
    stem = ctx.flow_stem
    source = classify(exc)
    reason = getattr(exc, "reason", None)

    screenshot = out_dir / f"{stem}.failed.png"
    html = out_dir / f"{stem}.failed.html"
    prompt = out_dir / f"{stem}.agent_prompt.txt"

    _safe(lambda: driver.page.screenshot(path=str(screenshot), full_page=True))
    _safe(lambda: html.write_text(driver.page.content(), encoding="utf-8"))

    branch = git_branch(ctx.config.root)
    text = build_agent_prompt(
        flow_path=Path(ctx.flow.get("__path__", stem)), branch=branch, source=source,
        error_text=str(exc), failed_index=failed_index, failed_action=failed_action,
        reason=reason, screenshot=screenshot, repro_command=ctx.config.repro_command,
    )
    _safe(lambda: prompt.write_text(text, encoding="utf-8"))
    log.wat(f"failure source={source} at step {failed_index} ({failed_action})", level="error")

    summary = {
        "result": "fail",
        "source": source,
        "flow": stem,
        "failed_step": failed_index,
        "failed_action": failed_action,
        "error": str(exc),
        "reason": reason,
        "branch": branch,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": {
            "screenshot": str(screenshot),
            "html": str(html),
            "agent_prompt": str(prompt),
            "trace": str(out_dir / "trace.zip"),
        },
    }
    log.write_json("run.json", summary)
    return summary


def write_success_summary(*, ctx: Any, log: Any, steps_run: int) -> dict[str, Any]:
    summary = {
        "result": "pass",
        "source": None,
        "flow": ctx.flow_stem,
        "steps_run": steps_run,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    log.write_json("run.json", summary)
    return summary


def _safe(fn: Any) -> None:
    try:
        fn()
    except Exception:
        pass
