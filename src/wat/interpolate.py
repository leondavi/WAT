"""``{{variable}}`` templating over the per-flow capture store.

Steps such as ``capture`` write values into a ``store`` dict; later steps reference
them with ``{{name}}`` placeholders in URLs, typed text, selectors, etc. This module
is pure and dependency-free so it is trivially unit-testable.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from .errors import StepFailure, SOURCE_FLOW_AUTHORING

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def interpolate(value: str, store: Mapping[str, Any]) -> str:
    """Replace every ``{{name}}`` in *value* with ``store[name]``.

    Raises :class:`StepFailure` (classified as a flow-authoring error) if a
    referenced variable was never captured, listing what *is* available so the
    author can fix the flow quickly.
    """

    def _replace(match: "re.Match[str]") -> str:
        key = match.group(1)
        if key not in store:
            raise StepFailure(
                f"Unknown variable '{{{{{key}}}}}'. Available: {sorted(store)}",
                source=SOURCE_FLOW_AUTHORING,
            )
        return str(store[key])

    return _PLACEHOLDER.sub(_replace, value)


def maybe_interpolate(value: Any, store: Mapping[str, Any]) -> Any:
    """Interpolate only if *value* is a string; pass other types through unchanged."""
    return interpolate(value, store) if isinstance(value, str) else value


def interpolate_lenient(value: str, store: Mapping[str, Any]) -> str:
    """Replace only KNOWN ``{{name}}`` placeholders; leave unknown ones literal.

    Used for ``script`` fields, where ``{{...}}`` is often literal JS or app-template
    text (e.g. a Liquid/Jinja template typed into a form) rather than a WAT variable.
    A captured variable still interpolates; anything else is passed through verbatim.
    """
    def _replace(match: "re.Match[str]") -> str:
        key = match.group(1)
        return str(store[key]) if key in store else match.group(0)

    return _PLACEHOLDER.sub(_replace, value)


def maybe_interpolate_lenient(value: Any, store: Mapping[str, Any]) -> Any:
    return interpolate_lenient(value, store) if isinstance(value, str) else value
