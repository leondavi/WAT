"""Flow loading, canonicalization, and validation.

A flow file is ``fl_<name>.json`` with top-level ``{name, label?, base_url?,
description?, reset_conversation?, steps: [...]}``. Each step is
``{action, ...fields, comment?}``.

Canonicalization smooths over the two forks' historical divergence (Gurim's
``value`` vs Cells' ``text``) so action handlers only ever see one shape.
Validation powers ``--validate-only``: it catches unknown actions, missing required
fields, and unresolved ``{{var}}`` references **without launching a browser**.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .errors import SchemaError
from .registry import REGISTRY, Registry

_VAR_REF = re.compile(r"\{\{(\w+)\}\}")


# ---------------------------------------------------------------------------
# Loading + canonicalization
# ---------------------------------------------------------------------------

def load_flow(path: str | Path) -> dict[str, Any]:
    """Read and canonicalize a flow file. Raises :class:`SchemaError` if malformed."""
    path = Path(path)
    if not path.name.startswith("fl_") or path.suffix.lower() != ".json":
        raise SchemaError(f"flow file must match fl_<name>.json: {path.name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaError(f"cannot read flow {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list) or not data["steps"]:
        raise SchemaError(f"flow {path.name} must be an object with a non-empty 'steps' array")
    data["steps"] = [canonicalize_step(s, i) for i, s in enumerate(data["steps"])]
    return data


# Field aliases accepted for backward compatibility with the legacy Selenium forks.
# Keys are legacy names; values are the canonical names they map to.
_FIELD_ALIASES = {
    "text": "value",                 # Cells typed/expected value
    "source_selector": "from_selector",  # legacy real_drag
    "target_selector": "to_selector",    # legacy real_drag
    "js": "script",                  # legacy eval_js / assert_js script
}


def canonicalize_step(step: dict[str, Any], index: int = 0) -> dict[str, Any]:
    """Normalize a raw step to the canonical shape.

    Accepts legacy field names from the old Selenium forks so existing flows keep
    working without edits:

    * ``text`` -> ``value``
    * ``source_selector`` / ``target_selector`` -> ``from_selector`` / ``to_selector``
    * ``sleep`` with ``ms`` -> ``seconds`` (ms / 1000)
    """
    if not isinstance(step, dict) or "action" not in step:
        raise SchemaError(f"step #{index} must be an object with an 'action' key: {step!r}")
    s = dict(step)
    for legacy, canonical in _FIELD_ALIASES.items():
        if legacy in s and canonical not in s:
            s[canonical] = s[legacy]
    # sleep: legacy `ms` -> canonical `seconds`.
    if s.get("action") == "sleep" and "ms" in s and "seconds" not in s:
        try:
            s["seconds"] = float(s["ms"]) / 1000.0
        except (TypeError, ValueError):
            pass
    return s


def find_flows(flows_dir: str | Path) -> list[Path]:
    """Return sorted ``fl_*.json`` files in *flows_dir*."""
    return sorted(Path(flows_dir).glob("fl_*.json"))


def flow_labels(flow: dict[str, Any]) -> list[str]:
    """Normalize the ``label`` field (string or list) to a list of strings."""
    raw = flow.get("label")
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return []


# ---------------------------------------------------------------------------
# Validation (no browser)
# ---------------------------------------------------------------------------

def validate_flow(flow: dict[str, Any], registry: Registry = REGISTRY) -> list[str]:
    """Return a list of human-readable errors for *flow* (empty == valid)."""
    errors: list[str] = []
    if not flow.get("steps"):
        errors.append("flow has no steps")
        return errors

    produced: set[str] = set()  # variables available via capture/store_as
    for i, step in enumerate(flow["steps"]):
        action = step.get("action")
        prefix = f"step #{i} ({action})"

        if not action:
            errors.append(f"step #{i}: missing 'action'")
            continue
        if not registry.has(action):
            errors.append(f"{prefix}: unknown action (no core/extension/plugin handler)")
            continue

        meta = registry.get(action)
        for req in meta.required:
            if req not in step and not (req == "value" and "text" in step):
                errors.append(f"{prefix}: missing required field '{req}'")

        # {{var}} references must be produced by an earlier step.
        for ref in _referenced_vars(step):
            if ref not in produced:
                errors.append(f"{prefix}: references '{{{{{ref}}}}}' before it is captured")

        var = step.get("store_as") or (step.get("var") if action == "capture" else None)
        if var:
            produced.add(var)

    return errors


def validate_file(path: str | Path, registry: Registry = REGISTRY) -> list[str]:
    """Load + validate a single flow file, returning error strings."""
    try:
        flow = load_flow(path)
    except SchemaError as exc:
        return [str(exc)]
    return validate_flow(flow, registry)


# Documentation-only fields never carry live {{var}} references.
_DOC_FIELDS = {"comment", "description", "_comment"}


def _referenced_vars(step: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for key, value in step.items():
        if key in _DOC_FIELDS:
            continue
        if isinstance(value, str):
            refs.update(_VAR_REF.findall(value))
    return refs
