"""Exception hierarchy for WAT.

The type of exception raised during a run feeds failure *classification* (see
:mod:`wat.reporting`): a reader should be able to tell whether a failure came from
the framework, the browser, the app under test, or the flow author. Each exception
carries a ``source`` label used to populate ``run.json``.
"""

from __future__ import annotations

# Canonical failure sources, mirrored in run.json and the generated agent prompt.
SOURCE_WAT_ENGINE = "wat_engine"
SOURCE_BROWSER = "browser"
SOURCE_APP = "app"
SOURCE_FLOW_AUTHORING = "flow_authoring"


class WatError(Exception):
    """Base class for every WAT error. ``source`` classifies the failing layer."""

    source: str = SOURCE_WAT_ENGINE

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class WatEngineError(WatError):
    """A bug/limitation inside the framework itself (driver, plugin import, config)."""

    source = SOURCE_WAT_ENGINE


class ActionNotFound(WatError):
    """A step referenced an ``action`` that no core action, extension, or plugin registered."""

    source = SOURCE_FLOW_AUTHORING


class ActionAlreadyRegistered(WatEngineError):
    """Two handlers tried to claim the same action name without ``override=True``."""


class SchemaError(WatError):
    """A flow file is structurally invalid (bad JSON, missing required fields)."""

    source = SOURCE_FLOW_AUTHORING


class StepFailure(WatError):
    """A step failed. Defaults to the ``app`` layer — the common case is a real
    assertion about app state — but callers may override ``source`` (e.g. a driver
    timeout is ``wat_engine``, a console-error assertion is ``browser``)."""

    source = SOURCE_APP

    def __init__(self, message: str, *, source: str | None = None, step_index: int | None = None,
                 action: str | None = None, reason: str | None = None):
        super().__init__(message)
        if source is not None:
            self.source = source
        self.step_index = step_index
        self.action = action
        self.reason = reason


class AssertionFailure(StepFailure):
    """A ``assert_*`` step's condition was not met. Belongs to the ``app`` layer."""

    source = SOURCE_APP
