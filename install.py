#!/usr/bin/env python3
"""WAT one-shot, cross-platform installer.

Run this **once** after cloning / adding the WAT submodule and you can immediately
use WAT. It is intentionally dependency-free (standard library only) so it runs on a
bare Python on macOS, Linux, or Windows.

What it does (idempotently):

  1. Verify the running interpreter is Python >= 3.10.
  2. Create a dedicated virtualenv named ``.wat-venv`` in the WAT repo root
     (never a bare ``venv``/``.venv`` — the name keeps it unambiguous next to an
     app's other environments).
  3. Install the ``wat`` package (editable) plus any requested extras.
  4. Download the Playwright browser(s) into that venv.
  5. Prepare the temp log root and print its path.
  6. Self-verify (``wat --doctor`` when available, else ``wat --help``).
  7. Print how to invoke WAT.

Usage::

    python install.py [--app NAME] [--extras liveview,sql] [--all-browsers] [--dry-run]

The thin ``install.sh`` / ``install.ps1`` wrappers just locate a suitable Python and
exec this file.
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

# The venv always lives beside this script, at the repo root.
REPO_ROOT = Path(__file__).resolve().parent
VENV_DIR = REPO_ROOT / ".wat-venv"
MIN_PYTHON = (3, 10)


# ---------------------------------------------------------------------------
# Small console helpers
# ---------------------------------------------------------------------------

def _say(msg: str) -> None:
    print(f"[wat-install] {msg}", flush=True)


def _ok(msg: str) -> None:
    print(f"[wat-install] OK: {msg}", flush=True)


def _fail(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"[wat-install] ERROR: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Platform-specific venv paths
# ---------------------------------------------------------------------------

def venv_bin_dir() -> Path:
    """Return the scripts/bin directory inside the venv for the current OS."""
    return VENV_DIR / ("Scripts" if os.name == "nt" else "bin")


def venv_python() -> Path:
    """Path to the venv's Python interpreter (``python.exe`` on Windows)."""
    return venv_bin_dir() / ("python.exe" if os.name == "nt" else "python")


def activate_hint() -> str:
    """Human-readable activation command for the current OS."""
    if os.name == "nt":
        return str(venv_bin_dir() / "Activate.ps1")
    return f"source {venv_bin_dir() / 'activate'}"


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def check_python() -> None:
    if sys.version_info < MIN_PYTHON:
        _fail(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required, "
            f"but this is {platform.python_version()}. "
            "Re-run with a newer interpreter, e.g. `python3.12 install.py`."
        )
    _ok(f"Python {platform.python_version()} on {platform.system()}")


def create_venv(dry_run: bool) -> None:
    if venv_python().exists():
        _say(f".wat-venv already exists at {VENV_DIR} (reusing)")
        return
    _say(f"creating dedicated venv at {VENV_DIR}")
    if dry_run:
        return
    # Use the stdlib venv module of the *current* interpreter.
    _run([sys.executable, "-m", "venv", str(VENV_DIR)])
    _ok("venv created")


def pip_install(extras: list[str], dry_run: bool) -> None:
    spec = "."  # editable install of the package at REPO_ROOT
    if extras:
        spec = f".[{','.join(extras)}]"
    _say(f"installing wat{('[' + ','.join(extras) + ']') if extras else ''} (editable)")
    if dry_run:
        return
    py = str(venv_python())
    _run([py, "-m", "pip", "install", "--upgrade", "pip"])
    _run([py, "-m", "pip", "install", "-e", spec], cwd=REPO_ROOT)
    _ok("package installed")


def install_browsers(all_browsers: bool, dry_run: bool) -> None:
    target = [] if all_browsers else ["chromium"]
    _say(f"installing Playwright browser(s): {'all' if all_browsers else 'chromium'}")
    if dry_run:
        return
    _run([str(venv_python()), "-m", "playwright", "install", *target])
    _ok("browsers installed")


def prepare_log_root(app: str) -> Path:
    """Create <tmpdir>/wat/<app>/ so the first run has somewhere to write."""
    root = Path(tempfile.gettempdir()) / "wat" / app
    root.mkdir(parents=True, exist_ok=True)
    _ok(f"log root ready: {root}")
    return root


def self_verify(dry_run: bool) -> None:
    if dry_run:
        return
    py = str(venv_python())
    # Prefer the richer `--doctor` diagnostic when the CLI exposes it; fall back
    # to `--help` so a phase-0 install (before doctor lands) still verifies.
    for args in (["-m", "wat", "--doctor"], ["-m", "wat", "--help"]):
        proc = subprocess.run([py, *args], cwd=REPO_ROOT)
        if proc.returncode == 0:
            _ok(f"self-verify passed ({' '.join(args)})")
            return
    _fail("self-verify failed: `python -m wat` did not run cleanly")


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    """Run a subprocess, streaming output; abort the installer on failure."""
    printable = " ".join(cmd)
    _say(f"$ {printable}")
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
    if proc.returncode != 0:
        _fail(f"command failed ({proc.returncode}): {printable}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Install WAT into a dedicated .wat-venv.")
    p.add_argument("--app", default="wat", help="App name; namespaces the temp log dir (<tmp>/wat/<app>).")
    p.add_argument(
        "--extras",
        default="",
        help="Comma-separated optional extras to install, e.g. 'liveview,sql'.",
    )
    p.add_argument("--all-browsers", action="store_true", help="Install all Playwright browsers, not just chromium.")
    p.add_argument("--dry-run", action="store_true", help="Print the plan without creating the venv or installing.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    extras = [e.strip() for e in args.extras.split(",") if e.strip()]

    _say("WAT installer starting")
    check_python()
    create_venv(args.dry_run)
    pip_install(extras, args.dry_run)
    install_browsers(args.all_browsers, args.dry_run)
    prepare_log_root(args.app)
    self_verify(args.dry_run)

    print()
    _ok("WAT is ready.")
    _say("Invoke it either way:")
    _say(f"  {venv_bin_dir() / 'wat'} --help")
    _say(f"  {venv_python()} -m wat --help")
    _say(f"Or activate the venv first:  {activate_hint()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
