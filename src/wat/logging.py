"""Per-run, source-tagged diagnostic logging.

The central promise: a reader can tell **at a glance** whether a failure came from
WAT, the browser, or the app. Every human-readable line is prefixed with a channel
tag — ``[WAT]``, ``[BROWSER]``, ``[APP]``, or ``[STEP]`` — and each channel is also
persisted to its own file inside a per-run directory:

    <tmpdir>/wat/<app>/
      runs/<run_id>/
        wat.log       # engine: dispatch, config, driver lifecycle, timings
        browser.log   # page console + pageerror + network failures
        app.log       # tailed server-log slices (via tail_log)
        steps.jsonl   # one structured record per step
        run.json      # machine-readable summary (written by wat.reporting)
      latest -> runs/<run_id>

Kept deliberately small and dependency-free.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

# Channel tags.
WAT = "WAT"
BROWSER = "BROWSER"
APP = "APP"
STEP = "STEP"

_LEVELS = {"debug": 10, "info": 20, "warn": 30, "error": 40}


def run_root(app_name: str, log_dir: str | None) -> Path:
    """Return the base log directory for an app (``log_dir`` overrides the temp default)."""
    if log_dir:
        return Path(log_dir).expanduser().resolve()
    return Path(tempfile.gettempdir()) / "wat" / app_name


def make_run_id(flow_stem: str) -> str:
    """``<flow_stem>-<UTC-timestamp>-<pid>`` — sortable and collision-resistant."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{flow_stem}-{stamp}-{os.getpid()}"


class RunLogger:
    """Owns the per-run directory and its channel files.

    Use as a context manager so the file handles are always closed::

        with RunLogger(app="cells", log_dir=None, flow_stem="fl_smoke") as log:
            log.wat("starting")
            log.browser("console.error: boom")
    """

    def __init__(self, *, app: str, log_dir: str | None, flow_stem: str,
                 level: str = "info", echo: bool = True, keep_runs: int = 50):
        self.app_name = app  # NB: not `self.app` — that would shadow the app() channel method
        self.flow_stem = flow_stem
        self.level = _LEVELS.get(level, 20)
        self.echo = echo
        self.run_id = make_run_id(flow_stem)
        self.base = run_root(app, log_dir)
        self.dir = self.base / "runs" / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self._files: dict[str, TextIO] = {}
        self._steps: TextIO | None = None
        self._prune(keep_runs)
        self._link_latest()

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> "RunLogger":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        for fh in self._files.values():
            try:
                fh.close()
            except Exception:
                pass
        if self._steps:
            self._steps.close()

    # -- channels ----------------------------------------------------------

    def wat(self, message: str, level: str = "info") -> None:
        if _LEVELS.get(level, 20) >= self.level:
            self._emit(WAT, message, "wat.log")

    def browser(self, message: str) -> None:
        self._emit(BROWSER, message, "browser.log")

    def app(self, message: str) -> None:
        self._emit(APP, message, "app.log")

    def step(self, record: dict[str, Any]) -> None:
        """Append a structured per-step record to steps.jsonl and echo a summary line."""
        if self._steps is None:
            self._steps = (self.dir / "steps.jsonl").open("a", encoding="utf-8")
        self._steps.write(json.dumps(record, default=str) + "\n")
        self._steps.flush()
        idx = record.get("index", "?")
        action = record.get("action", "?")
        status = record.get("status", "?")
        dur = record.get("duration_ms", "?")
        self._emit(STEP, f"[{idx}] {action} -> {status} ({dur}ms)", None)

    def write_json(self, name: str, payload: dict[str, Any]) -> Path:
        """Write a JSON artifact (e.g. run.json) into the run dir; return its path."""
        path = self.dir / name
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path

    # -- internals ---------------------------------------------------------

    def _emit(self, tag: str, message: str, filename: str | None) -> None:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        line = f"{ts} [{tag}] {message}"
        if filename is not None:
            fh = self._files.get(filename)
            if fh is None:
                fh = (self.dir / filename).open("a", encoding="utf-8", buffering=1)
                self._files[filename] = fh
            fh.write(line + "\n")
        if self.echo:
            print(line, flush=True)

    def _link_latest(self) -> None:
        """Point ``<base>/latest`` at this run (best-effort; symlinks may be unavailable)."""
        latest = self.base / "latest"
        try:
            if latest.is_symlink() or latest.exists():
                latest.unlink()
            latest.symlink_to(self.dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            # e.g. Windows without privilege — record the pointer in a plain file instead.
            try:
                (self.base / "latest.txt").write_text(str(self.dir), encoding="utf-8")
            except OSError:
                pass

    def _prune(self, keep: int) -> None:
        """Keep only the most recent *keep* run directories."""
        runs_dir = self.base / "runs"
        if keep <= 0 or not runs_dir.exists():
            return
        runs = sorted((p for p in runs_dir.iterdir() if p.is_dir()), key=lambda p: p.name)
        for old in runs[:-keep]:
            _rmtree(old)


def _rmtree(path: Path) -> None:
    import shutil

    try:
        shutil.rmtree(path)
    except OSError:
        pass
