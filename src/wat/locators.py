"""Canonical selector resolution → Playwright ``Locator``.

A step targets an element with two fields:

    "by":       one of the kinds below (default "css")
    "selector": the value for that kind

Playwright's semantic locators (``role``, ``testid``, ``text``, ``label``,
``placeholder``) are first-class, alongside plain ``css``/``xpath``. Optional
refinements: ``has_text`` (filter) and ``index``/``nth`` (disambiguate matches).
"""

from __future__ import annotations

from typing import Any, Callable

from .errors import StepFailure, SOURCE_FLOW_AUTHORING

# Kinds that map to a raw Playwright selector string.
_STRING_KINDS: dict[str, Callable[[str], str]] = {
    "css": lambda s: s,
    "xpath": lambda s: s if s.startswith("xpath=") else f"xpath={s}",
    "id": lambda s: f"#{s}",
    "name": lambda s: f"[name='{s}']",
    "class": lambda s: s if s.startswith(".") else f".{s}",
    "tag": lambda s: s,
}


def resolve_locator(page: Any, step: dict[str, Any], resolve: Callable[[Any], Any]) -> Any:
    """Return a Playwright ``Locator`` for *step* on *page*.

    *resolve* interpolates ``{{var}}`` placeholders (usually ``ctx.resolve``).
    """
    by = step.get("by", "css")
    raw = step.get("selector")

    # Semantic locators take the selector as their primary argument.
    if by == "role":
        role = resolve(raw)
        if not role:
            raise StepFailure("by='role' requires 'selector' (the ARIA role)", source=SOURCE_FLOW_AUTHORING)
        name = resolve(step.get("name"))
        loc = page.get_by_role(role, name=name) if name else page.get_by_role(role)
    elif by == "testid":
        loc = page.get_by_test_id(resolve(raw))
    elif by == "text":
        loc = page.get_by_text(resolve(raw))
    elif by == "label":
        loc = page.get_by_label(resolve(raw))
    elif by == "placeholder":
        loc = page.get_by_placeholder(resolve(raw))
    elif by in _STRING_KINDS:
        if raw is None:
            raise StepFailure(f"by='{by}' requires 'selector'", source=SOURCE_FLOW_AUTHORING)
        loc = page.locator(_STRING_KINDS[by](str(resolve(raw))))
    else:
        raise StepFailure(
            f"unsupported selector kind by='{by}'. "
            f"Allowed: role, testid, text, label, placeholder, {', '.join(sorted(_STRING_KINDS))}",
            source=SOURCE_FLOW_AUTHORING,
        )

    # Optional refinements.
    has_text = step.get("has_text")
    if has_text:
        loc = loc.filter(has_text=resolve(has_text))
    index = step.get("index", step.get("nth"))
    if index is not None:
        loc = loc.nth(int(index))
    return loc
