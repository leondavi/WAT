"""Core action modules.

Importing this package imports each module below, whose ``@register_action``
decorators populate the global registry. Import it once at startup (the CLI does)
so all core actions are available before any flow runs. Extensions and app plugins
register on top afterwards.
"""

from __future__ import annotations

# Order matters only in that core registers first; within core it is irrelevant.
from . import navigation  # noqa: F401
from . import interaction  # noqa: F401
from . import capture  # noqa: F401
from . import scripting  # noqa: F401
from . import assertions  # noqa: F401
from . import browser  # noqa: F401
from . import network  # noqa: F401
