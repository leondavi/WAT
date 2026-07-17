"""Playwright driver: browser/context/page lifecycle + diagnostics capture.

This is the only module that imports Playwright, and it does so *lazily* (inside
:meth:`Driver.start`) so ``import wat`` and the pure-logic unit tests never require a
browser. The driver also owns the console / page-error / network buffers that back
``assert_no_console_errors``, ``assert_console_match``, and the browser diagnostics
channel — replacing Selenium's ``goog:loggingPrefs`` capture with native listeners.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import WatConfig

# Map friendly browser names to (playwright_type, default channel).
_BROWSERS = {
    "chromium": ("chromium", None),
    "chrome": ("chromium", "chrome"),
    "edge": ("chromium", "msedge"),
    "firefox": ("firefox", None),
    "webkit": ("webkit", None),
}


def build_launch_kwargs(config: WatConfig) -> tuple[str, dict[str, Any]]:
    """Return (playwright_browser_kind, launch_kwargs) for a config.

    Pure and side-effect-free so the headed / slow-mo / devtools / channel logic can
    be unit-tested without launching a browser.
    """
    kind, default_channel = _BROWSERS.get(config.browser, ("chromium", None))
    kwargs: dict[str, Any] = {"headless": config.headless}
    channel = config.channel or default_channel
    if channel:
        kwargs["channel"] = channel
    if config.slow_mo_ms > 0:
        kwargs["slow_mo"] = config.slow_mo_ms
    # devtools only makes sense for a visible chromium session.
    if config.devtools and not config.headless and kind == "chromium":
        kwargs["devtools"] = True
    return kind, kwargs


def _resolve_storage_state(config: WatConfig) -> tuple[Path | None, bool]:
    """Return (resolved storage-state path, exists?). Relative paths join config.root."""
    if not config.storage_state:
        return None, False
    p = Path(config.storage_state)
    if not p.is_absolute():
        p = Path(config.root) / p
    return p, p.exists()


def build_context_kwargs(config: WatConfig) -> dict[str, Any]:
    """Return the ``browser.new_context`` kwargs for a config.

    Pure and side-effect-free (mirrors :func:`build_launch_kwargs`) so the viewport /
    video / storage-state wiring is unit-testable without launching a browser. A
    configured-but-missing storage-state file is simply omitted here; the caller warns.
    """
    kwargs: dict[str, Any] = {
        "viewport": {"width": config.viewport_width, "height": config.viewport_height},
    }
    if config.video != "off":
        kwargs["record_video_dir"] = str((config.artifacts_path() / "video"))
    path, exists = _resolve_storage_state(config)
    if path and exists:
        kwargs["storage_state"] = str(path)
    return kwargs


class BrowserSession:
    """A launched Playwright browser that can be reused across many flows.

    Launching a browser process is the expensive part (~300-500ms); a ``--all`` run
    creates ONE session and gives each flow its own fresh :class:`Driver` context on
    the shared browser, cutting per-flow startup dramatically. A session is bound to
    the thread that started it (Playwright's sync API is not thread-safe), so parallel
    workers each use their own session.
    """

    def __init__(self, config: WatConfig, log: Any):
        self.config = config
        self.log = log
        self._pw: Any = None
        self.browser: Any = None

    def start(self) -> "BrowserSession":
        from playwright.sync_api import sync_playwright

        kind, launch_kwargs = build_launch_kwargs(self.config)
        self._pw = sync_playwright().start()
        launcher = getattr(self._pw, kind)
        mode = "headed" if not self.config.headless else "headless"
        extra = f", slow_mo={self.config.slow_mo_ms}ms" if self.config.slow_mo_ms else ""
        if launch_kwargs.get("channel"):
            extra += f", channel={launch_kwargs['channel']}"
        self.log.wat(f"launching {self.config.browser} ({mode}{extra})")
        self.browser = launcher.launch(**launch_kwargs)
        return self

    def new_driver(self, log: Any) -> "Driver":
        """Create a Driver bound to a fresh context on this shared browser."""
        driver = Driver(self.config, log, session=self)
        driver.start()
        return driver

    def close(self) -> None:
        for closer in (self.browser, self._pw):
            try:
                if closer is not None:
                    closer.stop() if closer is self._pw else closer.close()
            except Exception:
                pass


class Driver:
    """Owns a Playwright *context* + page (on a shared or private browser) and the
    per-run diagnostic buffers."""

    def __init__(self, config: WatConfig, log: Any, session: "BrowserSession | None" = None):
        self.config = config
        self.log = log
        self._session = session
        self._owns_session = session is None
        self.browser: Any = None
        self.context: Any = None
        self.page: Any = None
        self._stream: bool = False  # stream browser signals to the log live (set in start())
        # Diagnostic buffers (drained by assertions / reporting).
        self.console_messages: list[dict[str, str]] = []
        self.page_errors: list[str] = []
        self.network_failures: list[dict[str, Any]] = []

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Open a traced context + page on the browser and wire diagnostic listeners.

        When no session was supplied, a private one is launched (single-flow path),
        preserving the original one-browser-per-flow behavior.
        """
        if self._session is None:
            self._session = BrowserSession(self.config, self.log).start()
            self._owns_session = True
        self.browser = self._session.browser
        self._stream = self.config.stream_console_effective()

        if self.config.video != "off":
            self._video_dir()  # ensure the dir exists (Playwright records into it)
        context_kwargs = build_context_kwargs(self.config)
        # A configured storage-state file that doesn't exist yet (e.g. the setup flow
        # hasn't run) is a warning, not a failure — start with a fresh context.
        ss_path, ss_exists = _resolve_storage_state(self.config)
        if ss_path and not ss_exists:
            self.log.wat(f"storage_state {ss_path} not found; starting with a fresh context", level="warn")
        elif ss_path:
            self.log.wat(f"restoring storage_state from {ss_path}")
        self.context = self.browser.new_context(**context_kwargs)
        self.context.set_default_timeout(self.config.wait_ms)

        if self.config.trace != "off":
            self.context.tracing.start(screenshots=True, snapshots=True, sources=True)

        self.page = self.context.new_page()
        self._wire_listeners(self.page)

    def stop(self, *, save_trace: bool, trace_path: Path | None = None) -> None:
        """Stop tracing, close the context, and close the browser iff we own it."""
        try:
            if self.config.trace != "off" and self.context is not None:
                if save_trace and trace_path is not None:
                    self.context.tracing.stop(path=str(trace_path))
                else:
                    self.context.tracing.stop()
        except Exception:  # tracing is best-effort; never mask the real result
            pass
        try:
            if self.context is not None:
                self.context.close()
        except Exception:
            pass
        # Only tear down the browser/playwright if this driver launched its own.
        if self._owns_session and self._session is not None:
            self._session.close()

    # -- diagnostic buffers ------------------------------------------------

    def console_errors(self) -> list[str]:
        """Console messages of type ``error`` plus uncaught page errors."""
        errs = [m["text"] for m in self.console_messages if m["type"] == "error"]
        return errs + list(self.page_errors)

    def console_matches(self, pattern: str) -> list[str]:
        """All console message texts matching *pattern* (regex)."""
        rx = re.compile(pattern)
        return [m["text"] for m in self.console_messages if rx.search(m["text"])]

    def drain_diagnostics(self) -> None:
        """Forward buffered browser signals to the [BROWSER] log channel.

        No-op when streaming live (they were already logged as they arrived)."""
        if self._stream:
            return
        for msg in self.console_messages:
            if msg["type"] in ("error", "warning"):
                self.log.browser(f"console.{msg['type']}: {msg['text']}")
        for err in self.page_errors:
            self.log.browser(f"pageerror: {err}")
        for fail in self.network_failures:
            self.log.browser(f"network {fail.get('status', 'FAILED')}: {fail.get('url')}")

    # -- internals ---------------------------------------------------------

    def _wire_listeners(self, page: Any) -> None:
        page.on("console", self._on_console)
        page.on("pageerror", self._on_pageerror)
        page.on("requestfailed", self._on_requestfailed)
        page.on("response", self._on_response)

    def _on_console(self, msg: Any) -> None:
        entry = {"type": msg.type, "text": msg.text}
        self.console_messages.append(entry)
        # Stream errors/warnings live so a watcher sees them the instant they occur.
        if self._stream and msg.type in ("error", "warning"):
            self.log.browser(f"console.{msg.type}: {msg.text}")

    def _on_pageerror(self, err: Any) -> None:
        self.page_errors.append(str(err))
        if self._stream:
            self.log.browser(f"pageerror: {err}")

    def _on_requestfailed(self, req: Any) -> None:
        entry = {"url": req.url, "status": "FAILED", "error": getattr(req.failure, "error_text", None)}
        self.network_failures.append(entry)
        if self._stream:
            self.log.browser(f"request failed: {req.url}")

    def _on_response(self, response: Any) -> None:
        try:
            if response.status >= 400:
                self.network_failures.append({"url": response.url, "status": response.status})
                if self._stream:
                    self.log.browser(f"HTTP {response.status}: {response.url}")
        except Exception:
            pass

    def _video_dir(self) -> Path:
        d = self.config.artifacts_path() / "video"
        d.mkdir(parents=True, exist_ok=True)
        return d
