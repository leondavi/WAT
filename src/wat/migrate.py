"""Flow migration: legacy Selenium ``fl_*.json`` -> canonical Playwright form.

Most legacy flows are already close to the canonical schema (they share the
``action``/``by``/``selector``/``value`` model), so migration is mostly:

  * normalize ``text`` -> ``value``;
  * map Selenium-only locators (``link_text``/``partial_link_text``) to ``text``;
  * flag steps that need a human look (async ``assert_js`` callbacks, ``real_drag``);
  * report actions with no registered handler (they need an extension or app plugin).

``migrate_flow`` is pure (returns a new flow + a report) so it is easy to test. The
CLI ``--migrate`` mode rewrites files only when ``--write`` is passed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .registry import REGISTRY, Registry
from .schema import find_flows

# Selenium locators with a canonical replacement.
_LOCATOR_MAP = {"link_text": "text", "partial_link_text": "text"}


def migrate_step(step: dict[str, Any], registry: Registry = REGISTRY) -> tuple[dict[str, Any], list[str]]:
    """Return (canonical_step, review_notes) for a single legacy step."""
    s = dict(step)
    notes: list[str] = []
    action = s.get("action")

    # text -> value
    if "text" in s and "value" not in s:
        s["value"] = s.pop("text")

    # legacy locators
    by = s.get("by")
    if by in _LOCATOR_MAP:
        s["by"] = _LOCATOR_MAP[by]
        notes.append(f"mapped by='{by}' -> by='{s['by']}' (verify the selector)")

    # async assert_js callbacks differ under Playwright evaluate
    if action in ("assert_js", "eval_js", "evaluate"):
        script = str(s.get("script", ""))
        if "arguments[" in script or "done(" in script or "callback(" in script:
            notes.append("assert_js uses a Selenium async callback; rewrite to `return new Promise(...)`")

    if action in ("real_drag", "drag_and_drop"):
        notes.append("real_drag semantics differ under Playwright; verify the drag")

    if action and not registry.has(action):
        notes.append(f"action '{action}' has no handler — needs an extension or app plugin")

    return s, notes


def migrate_flow(flow: dict[str, Any], registry: Registry = REGISTRY) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return (canonical_flow, report) where report is a list of per-step review items."""
    out = dict(flow)
    report: list[dict[str, Any]] = []
    new_steps = []
    for i, step in enumerate(flow.get("steps", [])):
        new_step, notes = migrate_step(step, registry)
        new_steps.append(new_step)
        for note in notes:
            report.append({"step": i, "action": step.get("action"), "note": note})
    out["steps"] = new_steps
    return out, report


def migrate_dir(flows_dir: str | Path, *, write: bool = False,
                registry: Registry = REGISTRY) -> dict[str, list[dict[str, Any]]]:
    """Migrate every flow in *flows_dir*. Returns {flow_name: report}. Writes files iff *write*."""
    results: dict[str, list[dict[str, Any]]] = {}
    for path in find_flows(flows_dir):
        try:
            flow = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            results[path.name] = [{"step": None, "action": None, "note": f"unreadable: {exc}"}]
            continue
        new_flow, report = migrate_flow(flow, registry)
        results[path.name] = report
        if write:
            path.write_text(json.dumps(new_flow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return results
