"""Action and hook registries — the extensibility core.

The forks' giant ``if action == ...`` dispatch collapses into a dict lookup here.
Core actions, optional extensions, and per-app plugins all register into the SAME
:data:`REGISTRY`, so a plugin action is indistinguishable from a built-in at dispatch
time. Import order decides precedence: core first, then extensions, then app plugins
(later registration wins only with ``override=True``).

A handler receives the :class:`~wat.context.StepContext` (the current step is
``ctx.step``) and returns one of:

    * ``None`` / ``True``           -> pass
    * ``False``                     -> fail
    * ``{"pass": bool, "reason": str, ...}`` -> pass/fail + diagnostics

The registry also stores lightweight metadata (``required`` fields, description)
that powers ``--validate-only``, ``--print-actions``, and the generated catalog.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Optional, Union

from .errors import ActionAlreadyRegistered, ActionNotFound

if TYPE_CHECKING:  # avoid a runtime import cycle (context imports nothing heavy, but keep it clean)
    from .context import StepContext

# Handler + hook signatures.
ActionResult = Union[None, bool, dict]
ActionHandler = Callable[["StepContext"], ActionResult]
HookFn = Callable[["StepContext"], None]
LoginProvider = Callable[["StepContext"], None]

HOOK_PHASES = ("before_flow", "after_flow", "before_step", "after_step")


@dataclass
class ActionMeta:
    """Metadata attached to a registered action (drives validation + docs)."""

    name: str
    handler: ActionHandler
    required: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    description: str = ""
    group: str = "core"


class Registry:
    """Holds actions, hooks, the pluggable login provider, and the reset hook."""

    def __init__(self) -> None:
        self._actions: dict[str, ActionMeta] = {}
        self._hooks: dict[str, list[HookFn]] = defaultdict(list)
        self._login_provider: Optional[LoginProvider] = None
        self._reset_hook: Optional[HookFn] = None

    # -- registration decorators ------------------------------------------

    def action(self, name: str, *, override: bool = False, required: tuple[str, ...] = (),
               aliases: tuple[str, ...] = (), description: str = "", group: str = "core"
               ) -> Callable[[ActionHandler], ActionHandler]:
        """Decorator: register *fn* as the handler for step action *name*."""

        def deco(fn: ActionHandler) -> ActionHandler:
            meta = ActionMeta(name=name, handler=fn, required=required,
                              aliases=aliases, description=description or (fn.__doc__ or "").strip().split("\n")[0],
                              group=group)
            for key in (name, *aliases):
                if key in self._actions and not override:
                    raise ActionAlreadyRegistered(
                        f"action '{key}' already registered by {self._actions[key].handler!r}; "
                        "pass override=True to replace it"
                    )
                self._actions[key] = meta
            return fn

        return deco

    def hook(self, phase: str) -> Callable[[HookFn], HookFn]:
        """Decorator: register *fn* to run at a lifecycle *phase* (see HOOK_PHASES)."""
        if phase not in HOOK_PHASES:
            raise ValueError(f"unknown hook phase {phase!r}; valid: {HOOK_PHASES}")

        def deco(fn: HookFn) -> HookFn:
            self._hooks[phase].append(fn)
            return fn

        return deco

    def login_provider(self, fn: LoginProvider) -> LoginProvider:
        """Decorator: register the app's auth handler backing the ``login`` action."""
        self._login_provider = fn
        return fn

    def reset(self, fn: HookFn) -> HookFn:
        """Decorator: register a pre-flow reset hook (e.g. wipe app state)."""
        self._reset_hook = fn
        return fn

    # -- lookup ------------------------------------------------------------

    def get(self, name: str) -> ActionMeta:
        try:
            return self._actions[name]
        except KeyError:
            raise ActionNotFound(
                f"unknown action '{name}' — no core action, extension, or plugin registered it"
            )

    def has(self, name: str) -> bool:
        return name in self._actions

    def hooks(self, phase: str) -> list[HookFn]:
        return list(self._hooks.get(phase, ()))

    def get_login_provider(self) -> Optional[LoginProvider]:
        return self._login_provider

    def get_reset_hook(self) -> Optional[HookFn]:
        return self._reset_hook

    def names(self) -> list[str]:
        """Sorted unique canonical action names (aliases excluded)."""
        return sorted({m.name for m in self._actions.values()})

    def catalog(self) -> list[ActionMeta]:
        """Unique action metadata, sorted by group then name (for --print-actions/docs)."""
        seen: dict[str, ActionMeta] = {}
        for meta in self._actions.values():
            seen[meta.name] = meta
        return sorted(seen.values(), key=lambda m: (m.group, m.name))


# The process-global registry. Core action modules populate it on import.
REGISTRY = Registry()

# Public decorator aliases (re-exported from wat/__init__.py).
register_action = REGISTRY.action
register_hook = REGISTRY.hook
login_provider = REGISTRY.login_provider
reset_hook = REGISTRY.reset
