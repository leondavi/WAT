"""The :class:`StepContext` passed to every action handler and hook.

It bundles everything a handler needs — the live page, the capture store, config,
the current step, and the run logger — plus a few convenience helpers so handlers
stay short. It deliberately avoids importing Playwright types at runtime (they are
duck-typed as ``Any``) so the assertion/interaction logic can be unit-tested against
a lightweight fake page with no browser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import WatConfig
from .interpolate import maybe_interpolate, maybe_interpolate_lenient


# Schemes/prefixes that are already fully-qualified and must not be prefixed with base_url.
_ABSOLUTE_PREFIXES = ("http://", "https://", "data:", "about:", "file:", "blob:")


def resolve_url(base_url: str, path_or_url: str) -> str:
    """Join *base_url* and *path_or_url*, leaving already-absolute URLs untouched."""
    if path_or_url.startswith(_ABSOLUTE_PREFIXES):
        return path_or_url
    return f"{base_url.rstrip('/')}/{path_or_url.lstrip('/')}"


@dataclass
class StepContext:
    """Per-step execution context. ``step`` is swapped for each step in the flow."""

    page: Any                      # Playwright Page (or a fake in tests)
    browser_context: Any           # Playwright BrowserContext
    driver: Any                    # the WAT Driver (console/network buffers, lifecycle)
    config: WatConfig
    flow: dict[str, Any]
    flow_stem: str
    log: Any                       # wat.logging.RunLogger
    store: dict[str, Any] = field(default_factory=dict)   # {{var}} capture store
    state: dict[str, Any] = field(default_factory=dict)   # free per-flow scratch
    step: dict[str, Any] = field(default_factory=dict)    # the current step

    # -- convenience helpers ----------------------------------------------

    @property
    def base_url(self) -> str:
        # A flow may override the config base_url; the runner sets flow["base_url"].
        return self.flow.get("base_url") or self.config.base_url

    def resolve(self, value: Any) -> Any:
        """Interpolate ``{{var}}`` placeholders from the capture store."""
        return maybe_interpolate(value, self.store)

    def url(self, path: str) -> str:
        """Resolve a flow path against the effective base URL, interpolating first."""
        return resolve_url(self.base_url, self.resolve(path))

    def field(self, name: str, default: Any = None, *, required: bool = False,
              lenient: bool = False) -> Any:
        """Read ``self.step[name]`` with interpolation; optionally require it.

        With ``lenient=True``, unknown ``{{...}}`` placeholders are left literal
        (used for ``script`` fields, where braces are often app/JS content).
        """
        if name not in self.step:
            if required:
                from .errors import StepFailure, SOURCE_FLOW_AUTHORING

                raise StepFailure(
                    f"step '{self.step.get('action')}' is missing required field '{name}'",
                    source=SOURCE_FLOW_AUTHORING,
                )
            return default
        if lenient:
            return maybe_interpolate_lenient(self.step[name], self.store)
        return self.resolve(self.step[name])

    def locator(self, step: dict[str, Any] | None = None) -> Any:
        """Build a Playwright locator from the canonical selector fields of a step."""
        from .locators import resolve_locator

        return resolve_locator(self.page, step or self.step, self.resolve)

    def timeout_ms(self) -> int:
        """Per-step ``timeout`` override, else the configured default wait."""
        raw = self.step.get("timeout")
        return int(raw) if raw is not None else self.config.wait_ms
