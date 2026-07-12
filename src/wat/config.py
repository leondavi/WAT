"""Configuration model and layered loader.

Precedence, lowest to highest:

    dataclass defaults
      < [tool.wat] in pyproject.toml   (declarative, CI-safe)
      < wat.toml                        (declarative, app root)
      < watconfig.py                    (Python escape hatch: dynamic values + plugin imports)
      < WAT_* environment variables
      < CLI flags                       (only flags the user actually passed)

Only ``watconfig.py`` may run arbitrary code, which is what lets an app compute a
dynamic ``base_url`` (e.g. from a docker-compose port) and import its plugins.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # 3.10: TOML files are simply skipped if tomllib is absent.
    tomllib = None  # type: ignore[assignment]


@dataclass
class WatConfig:
    """All knobs that shape a run. See ``CONTRACT.md`` for the authoritative docs."""

    base_url: str = "http://localhost:4000"
    flows_dir: str = "flows"
    artifacts_dir: str = "artifacts"

    # Diagnostics / logging (see wat.logging).
    log_dir: str | None = None            # default: <tmpdir>/wat/<app_name>
    log_level: str = "info"               # debug | info | warn | error
    app_name: str = "wat"                 # namespaces temp log + artifact dirs
    app_log_path: str | None = None       # server log tailed into the [APP] channel
    keep_runs: int = 50                   # prune to the last N per-run log dirs

    # Browser / driver.
    browser: str = "chromium"             # chromium | firefox | webkit
    channel: str | None = None            # branded channel, e.g. "chrome" / "msedge" / "chrome-beta"
    headless: bool = True                 # False = live/headed, visible browser
    slow_mo_ms: int = 0                    # delay each action by N ms (watch a live run)
    devtools: bool = False                 # open devtools (chromium, headed only)
    wait_ms: int = 10_000
    trace: str = "on-failure"             # off | on | on-failure
    video: str = "off"                    # off | on | on-failure

    # Live-run ergonomics.
    stream_console: bool | None = None     # stream [BROWSER] console/pageerror live; None = auto (on when headed)
    verbose_steps: bool | None = None      # log each step's intent before running; None = auto (on when live)
    pause_on_failure: bool = False         # in a headed run, hold the browser open on failure to inspect

    # Step robustness defaults (per-step keys override these).
    step_retries: int = 0
    soft_asserts: bool = False
    # Fail a flow if the page raised an uncaught JS exception (pageerror) during the run.
    # Off by default so it never surprises existing flows; assert_no_console_errors is explicit.
    fail_on_pageerror: bool = False

    # Extensibility.
    plugins: list[str] = field(default_factory=list)       # import strings
    extensions: list[str] = field(default_factory=list)    # e.g. ["liveview", "sql"]
    auth_provider: str | None = None
    reset_hook: str | None = None
    credentials_source: str | None = None

    # Failure reporting.
    repro_command: str = "python -m wat --flow {flow}"

    # Populated by the loader for path resolution; not user-set.
    root: str = "."

    # -- derived helpers ---------------------------------------------------

    def flows_path(self) -> Path:
        return (Path(self.root) / self.flows_dir).resolve()

    def artifacts_path(self) -> Path:
        return (Path(self.root) / self.artifacts_dir).resolve()

    def is_live(self) -> bool:
        """A 'live' run is one a human is watching: headed, or slowed down."""
        return (not self.headless) or self.slow_mo_ms > 0

    def stream_console_effective(self) -> bool:
        """Whether to stream browser console/errors live (auto-on for live runs)."""
        return self.is_live() if self.stream_console is None else self.stream_console

    def verbose_steps_effective(self) -> bool:
        """Whether to log each step's intent before running (auto-on for live runs)."""
        return self.is_live() if self.verbose_steps is None else self.verbose_steps


# Boolean-ish env values.
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _coerce(name: str, raw: str) -> Any:
    """Coerce a string (from env/TOML) to the dataclass field's type."""
    typ = {f.name: f.type for f in fields(WatConfig)}.get(name)
    if typ in ("bool", bool):
        low = raw.strip().lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        return bool(raw)
    if typ in ("int", int):
        return int(raw)
    return raw


def _apply(cfg: WatConfig, values: dict[str, Any]) -> WatConfig:
    """Return a copy of *cfg* with known keys from *values* applied (unknowns ignored)."""
    known = {f.name for f in fields(WatConfig)}
    updates = {k: v for k, v in values.items() if k in known and v is not None}
    return replace(cfg, **updates) if updates else cfg


def _load_toml(path: Path, table: str | None = None) -> dict[str, Any]:
    if tomllib is None or not path.exists():
        return {}
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    if table:
        for part in table.split("."):
            data = data.get(part, {}) if isinstance(data, dict) else {}
    return data if isinstance(data, dict) else {}


def _load_watconfig_py(path: Path) -> dict[str, Any]:
    """Import ``watconfig.py`` and read its ``WAT_CONFIG`` dict or ``get_config()``."""
    if not path.exists():
        return {}
    import importlib.util

    spec = importlib.util.spec_from_file_location("watconfig", path)
    if spec is None or spec.loader is None:
        return {}
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # may register plugins as a side effect
    if hasattr(module, "get_config"):
        result = module.get_config()  # type: ignore[attr-defined]
    else:
        result = getattr(module, "WAT_CONFIG", {})
    if isinstance(result, WatConfig):
        # Allow returning a full dataclass instance.
        return {f.name: getattr(result, f.name) for f in fields(WatConfig)}
    return dict(result) if isinstance(result, dict) else {}


def _env_overrides() -> dict[str, Any]:
    """Read WAT_* environment variables into config keys (e.g. WAT_BASE_URL)."""
    out: dict[str, Any] = {}
    for f in fields(WatConfig):
        raw = os.environ.get(f"WAT_{f.name.upper()}")
        if raw is not None:
            out[f.name] = _coerce(f.name, raw)
    return out


def load_config(root: str | Path = ".", cli_overrides: dict[str, Any] | None = None) -> WatConfig:
    """Build the effective :class:`WatConfig` by merging every layer for *root*.

    *cli_overrides* should contain **only** flags the user explicitly passed, so
    unset flags never clobber file/env config.
    """
    root = Path(root).resolve()
    cfg = WatConfig(root=str(root))

    cfg = _apply(cfg, _load_toml(root / "pyproject.toml", table="tool.wat"))
    cfg = _apply(cfg, _load_toml(root / "wat.toml"))
    cfg = _apply(cfg, _load_watconfig_py(root / "watconfig.py"))
    cfg = _apply(cfg, _env_overrides())
    if cli_overrides:
        cfg = _apply(cfg, cli_overrides)

    return replace(cfg, root=str(root))
