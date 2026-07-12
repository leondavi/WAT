"""JavaScript evaluation actions.

Playwright's ``page.evaluate`` awaits a returned Promise natively, so the Selenium
sync/async split (``execute_script`` vs ``execute_async_script``) disappears: an
``assert_js`` that does ``return new Promise(...)`` just works.
"""

from __future__ import annotations

import re

from ..context import StepContext
from ..errors import StepFailure, SOURCE_FLOW_AUTHORING
from ..registry import register_action

# Matches a script that is ALREADY a function expression at its start:
#   (…) => …      x => …      async (…) => …      function (…) {…}
# The anchor is important: an inner `r => …` inside a `return new Promise(...)`
# body must NOT make the whole script look pre-wrapped.
_FUNC_START = re.compile(r"^\s*(async\s+)?(function\b|\(|[A-Za-z_$][\w$]*\s*=>)")


def as_callable(script: str) -> str:
    """Wrap a raw script so Playwright's ``evaluate`` can run it.

    Accepts three shapes:
      * an arrow/function expression (``() => ...``, ``x => ...``, ``function ...``)
        -> used as-is
      * a statement body containing ``return``/``;``/newlines
        -> wrapped in ``() => { ... }``
      * a bare expression -> wrapped in ``() => ( ... )``
    """
    s = script.strip()
    if _FUNC_START.match(s):
        return s
    if "return" in s or ";" in s or "\n" in s:
        return f"() => {{ {s} }}"
    return f"() => ({s})"


def _run_script(ctx: StepContext):
    # lenient: {{...}} inside a script is usually literal JS/app-template content.
    script = ctx.field("script", required=True, lenient=True)
    return ctx.page.evaluate(as_callable(str(script)))


@register_action("eval_js", aliases=("evaluate",), required=("script",), group="scripting",
                 description="Evaluate JS (Promise-aware); result captured but not asserted.")
def eval_js(ctx: StepContext) -> None:
    result = _run_script(ctx)
    var = ctx.step.get("store_as")
    if var:
        ctx.store[var] = result


@register_action("exec", required=("command",), group="scripting",
                 description="Run a guarded shell command (opt-in via config.allow_exec).")
def exec_(ctx: StepContext) -> None:
    import subprocess

    if not getattr(ctx.config, "allow_exec", False):
        raise StepFailure("action 'exec' is disabled; set allow_exec=true in config to enable",
                          source=SOURCE_FLOW_AUTHORING)
    command = ctx.field("command", required=True)
    proc = subprocess.run(command, shell=isinstance(command, str), cwd=ctx.config.root,
                          capture_output=True, text=True)
    ctx.log.app(f"exec `{command}` -> rc={proc.returncode}")
    if proc.returncode != 0:
        raise StepFailure(f"exec failed ({proc.returncode}): {proc.stderr.strip()}")
    var = ctx.step.get("store_as")
    if var:
        ctx.store[var] = proc.stdout.strip()
