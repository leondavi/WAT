"""WAT — Web Auto Tester.

A JSON-flow-driven, Playwright-based browser test runner. Importing ``wat`` registers
all core actions and exposes the public extension API used by app plugins::

    from wat import register_action, register_hook, login_provider, reset_hook, StepContext

    @register_action("open_dashboard", required=("id",))
    def open_dashboard(ctx: StepContext):
        ctx.page.goto(ctx.url(f"/dash/{ctx.field('id')}"))

Note: importing ``wat`` does NOT import Playwright (that happens lazily when a driver
starts), so plugins, validation, and unit tests work without a browser installed.
"""

from __future__ import annotations

__version__ = "0.1.0"

# Public extension API.
from .registry import (  # noqa: E402
    REGISTRY,
    register_action,
    register_hook,
    login_provider,
    reset_hook,
)
from .context import StepContext  # noqa: E402
from .config import WatConfig, load_config  # noqa: E402
from .errors import StepFailure, AssertionFailure, WatError  # noqa: E402

# Import core actions for their registration side effects.
from . import actions  # noqa: E402,F401


def run_flow(flow_path, config=None, registry=REGISTRY):
    """Convenience wrapper: run a single flow file. See :func:`wat.runner.run_flow`."""
    from .runner import run_flow as _run_flow

    return _run_flow(flow_path, config or WatConfig(), registry)


__all__ = [
    "__version__",
    "REGISTRY",
    "register_action",
    "register_hook",
    "login_provider",
    "reset_hook",
    "StepContext",
    "WatConfig",
    "load_config",
    "run_flow",
    "StepFailure",
    "AssertionFailure",
    "WatError",
]
