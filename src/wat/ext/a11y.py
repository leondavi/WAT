"""Accessibility extension: assert the page has no (or few) a11y violations.

Opt in with ``extensions = ["a11y"]``. Adds ``assert_a11y`` with two engines:

  * ``builtin`` (default, zero deps, hermetic) — injected JS running fast WCAG
    checks that catch the bulk of real regressions: images without alt text,
    buttons/links without an accessible name, unlabeled form controls, missing
    ``<html lang>``, duplicate ids, positive tabindex, and focusable content
    inside ``aria-hidden``.
  * ``axe`` (opt-in) — inject an ``axe.min.js`` the APP provides (config
    ``a11y_axe_path`` or step ``axe_path``) and run ``axe.run()`` with optional
    ``tags`` (e.g. ``["wcag2aa"]``). WAT deliberately does not bundle axe-core.

Step shape::

    {"action": "assert_a11y"}                                   # builtin, whole page
    {"action": "assert_a11y", "selector": "#main"}              # scope to a subtree
    {"action": "assert_a11y", "rules": ["img-alt", "control-name"]}
    {"action": "assert_a11y", "allow": 2}                       # tolerate N violations
    {"action": "assert_a11y", "engine": "axe", "tags": ["wcag2aa"]}

Violations are returned on the result dict, so the runner serializes them into the
failure reason / run log (same diagnostics path as ``assert_js``).
"""

from __future__ import annotations

from pathlib import Path

from ..context import StepContext
from ..errors import StepFailure, SOURCE_FLOW_AUTHORING
from ..registry import register_action

# Builtin checks. Receives [scopeSelector|null, rules|null]; returns
# {violations: [{rule, target, detail}]} or {error: "..."}. Rule ids are stable API.
_BUILTIN_JS = """([scopeSel, rules]) => {
  const root = scopeSel ? document.querySelector(scopeSel) : document;
  if (!root) return {error: 'a11y scope not found: ' + scopeSel};
  const v = [];
  const on = r => !rules || rules.includes(r);
  const vis = el => !el.closest('[hidden]') && el.getClientRects().length > 0;
  const ident = el => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    else if (el.getAttribute('name')) s += "[name='" + el.getAttribute('name') + "']";
    else if (el.className && typeof el.className === 'string')
      s += '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.');
    return s.slice(0, 80);
  };
  const push = (rule, el, detail) => v.push({rule, target: ident(el), detail});
  const q = sel => Array.from(root.querySelectorAll(sel)).filter(vis);
  const accName = el => (el.getAttribute('aria-label') || el.getAttribute('title')
    || (el.getAttribute('aria-labelledby') || '').trim()
    || (el.textContent || '').trim()
    || (el.querySelector && el.querySelector('img[alt]') ? el.querySelector('img[alt]').alt : '')
    || el.value || '');

  if (on('img-alt'))
    q("img:not([alt]):not([role='presentation']):not([role='none'])")
      .filter(el => !el.closest("[aria-hidden='true']"))
      .forEach(el => push('img-alt', el, 'image has no alt attribute'));

  if (on('control-name'))
    q("button, a[href], [role='button'], input[type='button'], input[type='submit']")
      .filter(el => !accName(el))
      .forEach(el => push('control-name', el, 'interactive control has no accessible name'));

  if (on('label'))
    q("select, textarea, input:not([type='hidden']):not([type='button']):not([type='submit'])" +
      ":not([type='reset']):not([type='image'])")
      .filter(el => !(el.labels && el.labels.length) && !el.closest('label')
        && !el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby')
        && !el.getAttribute('title'))
      .forEach(el => push('label', el, 'form control has no label'));

  if (on('html-lang') && !scopeSel && !(document.documentElement.lang || '').trim())
    push('html-lang', document.documentElement, 'html element has no lang attribute');

  if (on('dup-id')) {
    const seen = new Map();
    Array.from(root.querySelectorAll('[id]')).forEach(el => {
      if (seen.has(el.id)) push('dup-id', el, "duplicate id '" + el.id + "'");
      seen.set(el.id, true);
    });
  }

  if (on('tabindex-positive'))
    q('[tabindex]').filter(el => parseInt(el.getAttribute('tabindex'), 10) > 0)
      .forEach(el => push('tabindex-positive', el, 'positive tabindex disrupts focus order'));

  if (on('aria-hidden-focus'))
    Array.from(root.querySelectorAll("[aria-hidden='true']"))
      .flatMap(h => Array.from(h.querySelectorAll('a[href], button, input, select, textarea, [tabindex]')))
      .filter(el => !el.disabled && parseInt(el.getAttribute('tabindex') || '0', 10) >= 0 && vis(el))
      .forEach(el => push('aria-hidden-focus', el, 'focusable element inside aria-hidden'));

  return {violations: v};
}"""

# axe engine: assumes axe.min.js is already injected. Returns the same shape.
_AXE_JS = """([scopeSel, tags]) => {
  const opts = tags && tags.length ? {runOnly: {type: 'tag', values: tags}} : {};
  return axe.run(scopeSel || document, opts).then(r => ({
    violations: r.violations.map(x => ({
      rule: x.id,
      target: (x.nodes[0] && x.nodes[0].target.join(' ')) || '',
      detail: x.help + (x.impact ? ' [' + x.impact + ']' : ''),
      nodes: x.nodes.length,
    })),
  }));
}"""

_MAX_REPORTED = 10  # cap violations carried onto the result (reason is truncated anyway)


@register_action("assert_a11y", group="a11y",
                 description="Assert no accessibility violations (builtin checks or app-provided axe).")
def assert_a11y(ctx: StepContext) -> dict:
    scope = ctx.field("selector")
    allow = int(ctx.step.get("allow", 0))
    engine = ctx.step.get("engine", "builtin")

    if engine == "axe":
        _inject_axe(ctx)
        result = ctx.page.evaluate(_AXE_JS, [scope, ctx.step.get("tags")])
    elif engine == "builtin":
        result = ctx.page.evaluate(_BUILTIN_JS, [scope, ctx.step.get("rules")])
    else:
        raise StepFailure(f"assert_a11y: unknown engine '{engine}' (builtin | axe)",
                          source=SOURCE_FLOW_AUTHORING)

    if not isinstance(result, dict) or "violations" not in result:
        raise StepFailure(f"assert_a11y: {result.get('error') if isinstance(result, dict) else result!r}",
                          source=SOURCE_FLOW_AUTHORING)

    violations = result["violations"]
    ok = len(violations) <= allow
    return {
        "pass": ok,
        "reason": None if ok else f"{len(violations)} a11y violation(s) found (allowed {allow})",
        "count": len(violations),
        "violations": violations[:_MAX_REPORTED],
    }


def _inject_axe(ctx: StepContext) -> None:
    """Inject the app-provided axe.min.js into the page (idempotent per page)."""
    raw = ctx.step.get("axe_path") or getattr(ctx.config, "a11y_axe_path", None)
    if not raw:
        raise StepFailure(
            "assert_a11y engine 'axe' needs 'axe_path' (step) or config a11y_axe_path "
            "pointing at an axe.min.js provided by your app",
            source=SOURCE_FLOW_AUTHORING,
        )
    path = Path(str(raw))
    if not path.is_absolute():
        path = Path(ctx.config.root) / path
    if not path.exists():
        raise StepFailure(f"axe script not found: {path}", source=SOURCE_FLOW_AUTHORING)
    if not ctx.page.evaluate("() => typeof window.axe !== 'undefined'"):
        ctx.page.add_script_tag(content=path.read_text(encoding="utf-8"))
