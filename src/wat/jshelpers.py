"""Shared per-app JS helpers injected into every flow's pages.

Set ``helpers = "flows/helpers.js"`` in config (relative paths resolve against the app
root, like every other config path). The file is registered with Playwright's
``context.add_init_script``, so it runs in page context before any app script on
EVERY document the flow loads: the first ``open``, later navigations, reloads, and the
reset hook's own navigation. Flows then call the shared functions from ``assert_js`` /
``eval_js`` without redefining them, and editing the one file changes every flow.

Playwright runs every init script inside its own function wrapper, so top-level
``function``/``const`` declarations in the file stay LOCAL to it. Helpers must publish
what flows call on ``window`` (e.g. ``window.__watSend = async (...) => {...}``); local
declarations are fine for private internals. (No ``eval`` is used, so a strict page CSP
cannot block the injection.) A ``//# sourceURL`` is appended so stack traces and
pageerrors name the helpers file.

:func:`validate_helpers` backs ``wat --validate-only`` so a missing, unreadable, or
(when ``node`` is on PATH) syntactically invalid file is reported at validate time
rather than mid-run. This module never imports Playwright.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .config import WatConfig
from .errors import SOURCE_FLOW_AUTHORING, StepFailure


def helpers_path(config: WatConfig) -> Path | None:
    """Resolved path of the configured helpers file, or None when not configured."""
    raw = getattr(config, "helpers", None)
    if not raw:
        return None
    p = Path(raw)
    return p if p.is_absolute() else (Path(config.root) / p)


def _read(path: Path) -> str:
    """Read the helpers file as UTF-8. Raises OSError / UnicodeDecodeError."""
    if not path.is_file():
        raise FileNotFoundError(f"not a file: {path}")
    return path.read_text(encoding="utf-8")


def init_script(config: WatConfig) -> str | None:
    """The init-script source to inject, or None when no helpers are configured.

    Raises :class:`StepFailure` (source ``flow_authoring``) if the configured file
    cannot be read, so a broken config fails the flow up front with a clear message.
    """
    path = helpers_path(config)
    if path is None:
        return None
    try:
        source = _read(path)
    except (OSError, UnicodeDecodeError) as exc:
        raise StepFailure(f"helpers file {path} cannot be loaded: {exc}",
                          source=SOURCE_FLOW_AUTHORING) from exc
    return f"{source}\n//# sourceURL=wat-helpers/{path.name}\n"


def validate_helpers(config: WatConfig) -> list[str]:
    """Return human-readable problems with the configured helpers file (empty == ok)."""
    path = helpers_path(config)
    if path is None:
        return []
    try:
        _read(path)
    except FileNotFoundError:
        return [f"helpers file not found: {path}"]
    except (OSError, UnicodeDecodeError) as exc:
        return [f"helpers file {path} cannot be read: {exc}"]
    err = _syntax_check(path)
    return [f"helpers file {path} has a syntax error: {err}"] if err else []


def _syntax_check(path: Path) -> str | None:
    """Best-effort JS syntax check via ``node --check``; None if ok or node is absent.

    The source is piped on stdin so the file extension never matters to node.
    """
    node = shutil.which("node")
    if node is None:
        return None
    try:
        proc = subprocess.run([node, "--check", "-"], input=_read(path), capture_output=True,
                              text=True, timeout=30, check=False)
    except (OSError, UnicodeDecodeError, subprocess.TimeoutExpired):
        return None
    if proc.returncode == 0:
        return None
    # node prints "[stdin]:<line>\n<source>\n<caret>\n\nSyntaxError: ...\n    at ..."
    lines = [ln.strip() for ln in proc.stderr.splitlines() if ln.strip()]
    gist = next((ln for ln in lines if "Error" in ln and not ln.startswith("at ")), "invalid JS")
    where = lines[0].replace("[stdin]", "line") if lines and lines[0].startswith("[stdin]:") else ""
    return gist + (f" ({where})" if where else "")
