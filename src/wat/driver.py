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

# Map friendly browser names to (playwright_type, channel).
_BROWSERS = {
    "chromium": ("chromium", None),
    "chrome": ("chromium", "chrome"),
    "edge": ("chromium", "msedge"),
    "firefox": ("firefox", None),
    "webkit": ("webkit", None),
}


class Driver:
    """Owns a Playwright browser + context + page and the per-run diagnostic buffers."""

    def __init__(self, config: WatConfig, log: Any):
        self.config = config
        self.log = log
        self._pw: Any = None
        self.browser: Any = None
        self.context: Any = None
        self.page: Any = None
        # Diagnostic buffers (drained by assertions / reporting).
        self.console_messages: list[dict[str, str]] = []
        self.page_errors: list[str] = []
        self.network_failures: list[dict[str, Any]] = []

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Launch the browser, open a traced context, and wire diagnostic listeners."""
        from playwright.sync_api import sync_playwright

        kind, channel = _BROWSERS.get(self.config.browser, ("chromium", None))
        self._pw = sync_playwright().start()
        launcher = getattr(self._pw, kind)
        launch_kwargs: dict[str, Any] = {"headless": self.config.headless}
        if channel:
            launch_kwargs["channel"] = channel
        if self.config.slow_mo_ms > 0:
            launch_kwargs["slow_mo"] = self.config.slow_mo_ms
        # devtools only makes sense for a visible chromium session.
        if self.config.devtools and not self.config.headless and kind == "chromium":
            launch_kwargs["devtools"] = True
        mode = "headed" if not self.config.headless else "headless"
        extra = f", slow_mo={self.config.slow_mo_ms}ms" if self.config.slow_mo_ms else ""
        self.log.wat(f"launching {self.config.browser} ({mode}{extra})")
        self.browser = launcher.launch(**launch_kwargs)

        context_kwargs: dict[str, Any] = {"viewport": {"width": 1440, "height": 1024}}
        if self.config.video != "off":
            context_kwargs["record_video_dir"] = str(self._video_dir())
        self.context = self.browser.new_context(**context_kwargs)
        self.context.set_default_timeout(self.config.wait_ms)

        if self.config.trace != "off":
            self.context.tracing.start(screenshots=True, snapshots=True, sources=True)

        self.page = self.context.new_page()
        self._wire_listeners(self.page)

    def stop(self, *, save_trace: bool, trace_path: Path | None = None) -> None:
        """Stop tracing (saving to *trace_path* iff *save_trace*) and close everything."""
        try:
            if self.config.trace != "off" and self.context is not None:
                if save_trace and trace_path is not None:
                    self.context.tracing.stop(path=str(trace_path))
                else:
                    self.context.tracing.stop()
        except Exception:  # tracing is best-effort; never mask the real result
            pass
        for closer in (self.context, self.browser):
            try:
                if closer is not None:
                    closer.close()
            except Exception:
                pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:
            pass

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
        """Forward buffered browser signals to the [BROWSER] log channel."""
        for msg in self.console_messages:
            if msg["type"] in ("error", "warning"):
                self.log.browser(f"console.{msg['type']}: {msg['text']}")
        for err in self.page_errors:
            self.log.browser(f"pageerror: {err}")
        for fail in self.network_failures:
            self.log.browser(f"network {fail.get('status', 'FAILED')}: {fail.get('url')}")

    # -- internals ---------------------------------------------------------

    def _wire_listeners(self, page: Any) -> None:
        page.on("console", lambda m: self.console_messages.append({"type": m.type, "text": m.text}))
        page.on("pageerror", lambda e: self.page_errors.append(str(e)))
        page.on("requestfailed", lambda r: self.network_failures.append(
            {"url": r.url, "status": "FAILED", "error": getattr(r.failure, "error_text", None)}))
        page.on("response", self._on_response)

    def _on_response(self, response: Any) -> None:
        try:
            if response.status >= 400:
                self.network_failures.append({"url": response.url, "status": response.status})
        except Exception:
            pass

    def _video_dir(self) -> Path:
        d = self.config.artifacts_path() / "video"
        d.mkdir(parents=True, exist_ok=True)
        return d
