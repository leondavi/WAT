"""Command-line interface for WAT.

    wat --flow flows/fl_smoke.json          run one flow
    wat --all [--label sheet/]              run all (optionally filtered by label prefix)
    wat --list                              list discovered flows
    wat --validate-only [--all|--flow F]    lint flows without a browser
    wat --print-actions                     show the registered action catalog
    wat --doctor                            check the environment

Config comes from wat.toml / [tool.wat] / watconfig.py / WAT_* env, and any CLI flag
below overrides it (only flags you actually pass take effect).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import plugins
from .config import load_config, WatConfig
from .registry import REGISTRY
from .schema import find_flows, flow_labels, load_flow, validate_file


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wat", description="WAT — Web Auto Tester (Playwright).")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--flow", type=Path, help="Path to a single fl_<name>.json flow.")
    mode.add_argument("--all", action="store_true", help="Run all flows in the flows dir.")
    mode.add_argument("--list", action="store_true", help="List discovered flows and exit.")
    mode.add_argument("--print-actions", action="store_true", help="Print the action catalog and exit.")
    mode.add_argument("--doctor", action="store_true", help="Check the environment and exit.")
    mode.add_argument("--migrate", action="store_true", help="Report/convert legacy flows to canonical form.")

    p.add_argument("--write", action="store_true", help="With --migrate: rewrite flow files in place.")
    p.add_argument("--validate-only", action="store_true", help="Validate flows without running a browser.")
    p.add_argument("--label", help="Filter --all/--list by label prefix.")
    p.add_argument("--root", type=Path, default=Path.cwd(), help="App root for config discovery (default: cwd).")

    # Config overrides (default None so unset flags don't clobber file/env config).
    p.add_argument("--base-url")
    p.add_argument("--browser", choices=["chromium", "chrome", "edge", "firefox", "webkit"])
    p.add_argument("--headless", dest="headless", action="store_const", const=True, default=None)
    p.add_argument("--headed", dest="headless", action="store_const", const=False,
                   help="Run a visible (live) browser.")
    p.add_argument("--live", action="store_true",
                   help="Live mode: headed + slow-mo (250ms) so you can watch the run.")
    p.add_argument("--slow-mo", dest="slow_mo_ms", type=int, help="Delay each action by N ms.")
    p.add_argument("--devtools", dest="devtools", action="store_const", const=True, default=None,
                   help="Open devtools (headed chromium).")
    p.add_argument("--wait-ms", type=int)
    p.add_argument("--flows-dir")
    p.add_argument("--app", dest="app_name")
    p.add_argument("--log-dir")
    return p


def _overrides(args: argparse.Namespace) -> dict:
    keys = ("base_url", "browser", "headless", "slow_mo_ms", "devtools",
            "wait_ms", "flows_dir", "app_name", "log_dir")
    overrides = {k: getattr(args, k) for k in keys if getattr(args, k) is not None}
    # --live is a convenience: visible browser + gentle slow-mo (unless overridden).
    if getattr(args, "live", False):
        overrides.setdefault("headless", False)
        if args.headless is None:
            overrides["headless"] = False
        overrides.setdefault("slow_mo_ms", 250)
    return overrides


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.root, _overrides(args))

    # Load extensions then app plugins so they layer on top of core actions.
    plugins.load(list(cfg.extensions) + list(cfg.plugins), root=cfg.root)

    if args.print_actions:
        return _print_actions()
    if args.doctor:
        return _doctor(cfg)
    if args.migrate:
        return _migrate(cfg, args)
    if args.list:
        return _list(cfg, args.label)
    if args.validate_only:
        return _validate(cfg, args)
    if args.flow:
        return _run_one(cfg, args.flow)
    if args.all:
        return _run_all(cfg, args.label)

    build_parser().print_help()
    return 1


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def _run_one(cfg: WatConfig, flow: Path) -> int:
    from .runner import run_flow

    return run_flow(flow, cfg)


def _run_all(cfg: WatConfig, label: str | None) -> int:
    from .runner import run_flow

    flows = _filtered_flows(cfg, label)
    if not flows:
        print(f"No flows found in {cfg.flows_path()} (label={label!r})")
        return 1
    print(f"Running {len(flows)} flow(s)...")
    results = [(f, run_flow(f, cfg)) for f in flows]
    passed = [f for f, rc in results if rc == 0]
    failed = [f for f, rc in results if rc != 0]
    print("\n" + "=" * 60)
    print(f"RESULTS: {len(passed)} passed, {len(failed)} failed")
    for f in passed:
        print(f"  ✅  {f.name}")
    for f in failed:
        print(f"  ❌  {f.name}")
    return 1 if failed else 0


def _list(cfg: WatConfig, label: str | None) -> int:
    flows = _filtered_flows(cfg, label)
    if not flows:
        print(f"No flows found in {cfg.flows_path()}")
        return 0
    for path in flows:
        try:
            flow = load_flow(path)
            labels = ", ".join(flow_labels(flow))
            suffix = f"  [{labels}]" if labels else ""
            print(f"  {path.name:<45} {flow.get('name', path.stem)}{suffix}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {path.name}  (error: {exc})")
    return 0


def _validate(cfg: WatConfig, args: argparse.Namespace) -> int:
    targets = [args.flow] if args.flow else _filtered_flows(cfg, args.label)
    total_errors = 0
    for path in targets:
        errors = validate_file(path, REGISTRY)
        if errors:
            total_errors += len(errors)
            print(f"❌ {Path(path).name}")
            for e in errors:
                print(f"     {e}")
        else:
            print(f"✅ {Path(path).name}")
    print(f"\n{total_errors} error(s) across {len(targets)} flow(s).")
    return 1 if total_errors else 0


def _migrate(cfg: WatConfig, args: argparse.Namespace) -> int:
    from .migrate import migrate_dir

    flows_dir = args.flow.parent if args.flow else cfg.flows_path()
    results = migrate_dir(flows_dir, write=args.write, registry=REGISTRY)
    total_notes = 0
    for name, report in sorted(results.items()):
        if report:
            total_notes += len(report)
            print(f"⚠ {name}")
            for item in report:
                loc = f"step {item['step']} ({item['action']})" if item["step"] is not None else "flow"
                print(f"     {loc}: {item['note']}")
        else:
            print(f"✓ {name}")
    verb = "rewrote" if args.write else "analyzed"
    print(f"\n{verb} {len(results)} flow(s); {total_notes} item(s) need review.")
    if not args.write:
        print("Re-run with --write to apply the canonical rewrite.")
    return 0


def _print_actions() -> int:
    group = None
    for meta in REGISTRY.catalog():
        if meta.group != group:
            group = meta.group
            print(f"\n[{group}]")
        alias = f" (aliases: {', '.join(meta.aliases)})" if meta.aliases else ""
        req = f"  required={list(meta.required)}" if meta.required else ""
        print(f"  {meta.name:<24} {meta.description}{alias}{req}")
    return 0


def _doctor(cfg: WatConfig) -> int:
    ok = True
    print("WAT doctor")
    print(f"  config root : {cfg.root}")
    print(f"  base_url    : {cfg.base_url}")
    print(f"  flows_dir   : {cfg.flows_path()}")
    print(f"  log_dir     : {cfg.log_dir or '(temp default)'}")
    print(f"  actions     : {len(REGISTRY.names())} registered")
    try:
        import playwright  # noqa: F401

        print("  playwright  : installed ✅")
    except ImportError:
        ok = False
        print("  playwright  : MISSING ❌ — run install.py")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _filtered_flows(cfg: WatConfig, label: str | None) -> list[Path]:
    flows = find_flows(cfg.flows_path())
    if not label:
        return flows
    out = []
    for path in flows:
        try:
            if any(lbl.startswith(label) for lbl in flow_labels(load_flow(path))):
                out.append(path)
        except Exception:  # noqa: BLE001
            pass
    return out
