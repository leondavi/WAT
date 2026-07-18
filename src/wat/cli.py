"""Command-line interface for WAT.

    wat --flow flows/fl_smoke.json          run one flow
    wat --all [--label p/] [--grep x]       run all (one reused browser; filter by label/substring)
    wat --all --workers 4 --fail-fast       run in parallel; stop on first failure
    wat --all --report out.xml              write a JUnit report (--report-format junit|json)
    wat --list                              list discovered flows
    wat --record [--flow F]                 record a browser session into a draft flow
    wat --validate-only [--all|--flow F]    lint flows without a browser
    wat --print-actions                     show the registered action catalog
    wat --doctor                            check the environment + plugin/extension wiring

Config comes from wat.toml / [tool.wat] / watconfig.py / WAT_* env, and any CLI flag
below overrides it (only flags you actually pass take effect).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import plugins
from .config import load_config, WatConfig
from .registry import REGISTRY, HOOK_PHASES
from .schema import find_flows, flow_labels, load_flow, validate_file


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wat", description="WAT — Web Auto Tester (Playwright).")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--flow", type=Path, help="Path to a single fl_<name>.json flow.")
    mode.add_argument("--all", action="store_true", help="Run all flows in the flows dir.")
    mode.add_argument("--list", action="store_true", help="List discovered flows and exit.")
    mode.add_argument("--print-actions", action="store_true", help="Print the action catalog and exit.")
    mode.add_argument("--doctor", action="store_true", help="Check the environment and exit.")

    # --migrate is a standalone mode (not in the exclusive group) so it can take an
    # optional --flow target: `--migrate` migrates the whole flows dir, `--migrate --flow F`
    # just F's directory (see _migrate, which reads args.flow).
    p.add_argument("--migrate", action="store_true", help="Report/convert legacy flows to canonical form.")
    p.add_argument("--write", action="store_true", help="With --migrate: rewrite flow files in place.")
    # --record is standalone for the same reason: --flow optionally names its output file.
    p.add_argument("--record", action="store_true",
                   help="Open a headed browser and record interactions into a draft flow "
                        "(--flow names the output, default flows/fl_recorded.json).")
    p.add_argument("--validate-only", action="store_true", help="Validate flows without running a browser.")
    p.add_argument("--label", help="Filter --all/--list by label prefix.")
    p.add_argument("--grep", help="Filter --all/--list by substring of the flow file name, name, or label.")
    p.add_argument("--root", type=Path, default=Path.cwd(), help="App root for config discovery (default: cwd).")

    # --all orchestration.
    p.add_argument("--workers", type=int, help="Run flows in parallel with N workers (each its own browser).")
    p.add_argument("--fail-fast", dest="fail_fast", action="store_const", const=True, default=None,
                   help="Stop the run on the first failing flow.")
    p.add_argument("--report", help="Write an aggregate report for --all to this path.")
    p.add_argument("--report-format", choices=["junit", "json", "html"], default="junit",
                   help="Format for --report (default: junit).")

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
    p.add_argument("--channel", help="Branded browser channel, e.g. chrome, msedge, chrome-beta.")
    p.add_argument("--pause-on-failure", dest="pause_on_failure", action="store_const", const=True,
                   default=None, help="Headed: hold the browser open on failure to inspect.")
    p.add_argument("--stream-console", dest="stream_console", action="store_const", const=True,
                   default=None, help="Stream browser console/errors live (auto-on when headed).")
    p.add_argument("--storage-state", dest="storage_state",
                   help="Path to a saved storage state (cookies + localStorage) to restore into each flow.")
    p.add_argument("--update-baselines", dest="visual_update", action="store_const", const=True,
                   default=None, help="Visual: (re)write screenshot baselines instead of comparing.")
    p.add_argument("--trace", choices=["off", "on", "on-failure"], help="Playwright trace capture.")
    p.add_argument("--video", choices=["off", "on", "on-failure"], help="Video capture.")
    p.add_argument("--wait-ms", type=int)
    p.add_argument("--flows-dir")
    p.add_argument("--app", dest="app_name")
    p.add_argument("--log-dir")
    return p


def _overrides(args: argparse.Namespace) -> dict:
    keys = ("base_url", "browser", "channel", "headless", "slow_mo_ms", "devtools",
            "pause_on_failure", "stream_console", "trace", "video", "storage_state",
            "visual_update", "workers", "fail_fast", "wait_ms", "flows_dir", "app_name", "log_dir")
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

    # --doctor loads plugins resiliently itself (a broken plugin is a finding,
    # not a crash), so run it before the strict global load below.
    if args.doctor:
        return _doctor(cfg)

    # Load extensions then app plugins so they layer on top of core actions.
    plugins.load(list(cfg.extensions) + list(cfg.plugins), root=cfg.root)

    if args.print_actions:
        return _print_actions()
    if args.record:
        return _record(cfg, args)
    if args.migrate:
        return _migrate(cfg, args)
    if args.list:
        return _list(cfg, args)
    if args.validate_only:
        return _validate(cfg, args)
    if args.flow:
        return _run_one(cfg, args.flow)
    if args.all:
        return _run_all(cfg, args)

    build_parser().print_help()
    return 1


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def _run_one(cfg: WatConfig, flow: Path) -> int:
    from .runner import run_flow

    return run_flow(flow, cfg)


def _run_all(cfg: WatConfig, args: argparse.Namespace) -> int:
    from .runner import run_flows
    from . import reports

    flows = _filtered_flows(cfg, args.label, args.grep)
    if not flows:
        print(f"No flows found in {cfg.flows_path()} (label={args.label!r}, grep={args.grep!r})")
        return 1
    mode = f", {cfg.workers} workers" if cfg.workers and cfg.workers > 1 else ""
    print(f"Running {len(flows)} flow(s){mode}...")

    results = run_flows(flows, cfg)
    passed = [r for r in results if r.returncode == 0]
    failed = [r for r in results if r.returncode != 0]
    # A flow may expand into several results (a matrix case per row), so "skipped" counts
    # flow FILES that produced no result at all (e.g. cut off by --fail-fast), never cases.
    ran = {r.path for r in results}
    skipped = sum(1 for f in flows if f not in ran)

    print("\n" + "=" * 60)
    print(f"RESULTS: {len(passed)} passed, {len(failed)} failed, {skipped} skipped")
    for r in passed:
        print(f"  [PASS] {r.path.name}  ({r.duration_ms}ms)")
    for r in failed:
        why = f" - {r.source}: {r.message}" if r.message else ""
        print(f"  [FAIL] {r.path.name}  ({r.duration_ms}ms){why}")

    if args.report:
        path = reports.write_report(results, args.report, args.report_format)
        print(f"\nReport ({args.report_format}) written to {path}")
    return 1 if failed else 0


def _list(cfg: WatConfig, args: argparse.Namespace) -> int:
    flows = _filtered_flows(cfg, args.label, args.grep)
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
    targets = [args.flow] if args.flow else _filtered_flows(cfg, args.label, args.grep)
    total_errors = 0
    for path in targets:
        errors = validate_file(path, REGISTRY)
        if errors:
            total_errors += len(errors)
            print(f"[FAIL] {Path(path).name}")
            for e in errors:
                print(f"     {e}")
        else:
            print(f"[PASS] {Path(path).name}")
    print(f"\n{total_errors} error(s) across {len(targets)} flow(s).")
    return 1 if total_errors else 0


def _record(cfg: WatConfig, args: argparse.Namespace) -> int:
    from .recorder import record_flow

    out = args.flow or (cfg.flows_path() / "fl_recorded.json")
    out = Path(out)
    if not out.name.startswith("fl_"):
        print(f"Output flow must be named fl_<name>.json, got: {out.name}")
        return 1
    path = record_flow(cfg, out)
    print(f"Recorded flow written to {path}")
    print(f"Review it, then lint with: wat --validate-only --flow {path}")
    return 0


def _migrate(cfg: WatConfig, args: argparse.Namespace) -> int:
    from .migrate import migrate_dir

    flows_dir = args.flow.parent if args.flow else cfg.flows_path()
    results = migrate_dir(flows_dir, write=args.write, registry=REGISTRY)
    total_notes = 0
    for name, report in sorted(results.items()):
        if report:
            total_notes += len(report)
            print(f"[REVIEW] {name}")
            for item in report:
                loc = f"step {item['step']} ({item['action']})" if item["step"] is not None else "flow"
                print(f"     {loc}: {item['note']}")
        else:
            print(f"[OK]     {name}")
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
    """Pre-flight wiring check: config, plugins/extensions (loaded here so import
    failures are reported, not fatal), hooks/providers, actions, and Playwright."""
    ok = True
    print("WAT doctor")
    print(f"  config root : {cfg.root}")
    print(f"  base_url    : {cfg.base_url}")
    print(f"  flows_dir   : {cfg.flows_path()}")
    print(f"  log_dir     : {cfg.log_dir or '(temp default)'}")
    if cfg.storage_state:
        from .driver import _resolve_storage_state

        ss_path, ss_exists = _resolve_storage_state(cfg)
        print(f"  storage     : {ss_path}  ({'found' if ss_exists else 'MISSING - run the setup flow'})")

    core_actions = len(REGISTRY.names())
    ext_results = plugins.load_reporting(list(cfg.extensions), cfg.root)
    plug_results = plugins.load_reporting(list(cfg.plugins), cfg.root)

    def _report(label: str, results: list) -> bool:
        all_ok = True
        if not results:
            print(f"  {label:<12}: (none)")
            return True
        for i, (name, good, err) in enumerate(results):
            lbl = label if i == 0 else ""
            if good:
                print(f"  {lbl:<12}: {name}  ok")
            else:
                all_ok = False
                print(f"  {lbl:<12}: {name}  FAILED  {err}")
        return all_ok

    ok &= _report("extensions", ext_results)
    ok &= _report("plugins", plug_results)

    # Hook / provider wiring — confirms a plugin actually registered something.
    counts = ", ".join(f"{p}={len(REGISTRY.hooks(p))}" for p in HOOK_PHASES)
    print(f"  hooks       : {counts}")
    print(f"  reset hook  : {'yes' if REGISTRY.get_reset_hook() else 'no'}")
    print(f"  login prov. : {'yes' if REGISTRY.get_login_provider() else 'no'}")
    added = len(REGISTRY.names()) - core_actions
    print(f"  actions     : {len(REGISTRY.names())} registered ({core_actions} core + {added} from ext/plugins)")

    try:
        import playwright  # noqa: F401

        print("  playwright  : installed  ok")
    except ImportError:
        ok = False
        print("  playwright  : MISSING  run install.py")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _filtered_flows(cfg: WatConfig, label: str | None, grep: str | None = None) -> list[Path]:
    """Discover flows, optionally filtered by label prefix and/or a substring (grep)
    matched against the file name, flow name, or any label."""
    flows = find_flows(cfg.flows_path())
    if not label and not grep:
        return flows
    needle = grep.lower() if grep else None
    out = []
    for path in flows:
        try:
            flow = load_flow(path)
        except Exception:  # noqa: BLE001 — malformed flow: skip during filtering
            continue
        labels = flow_labels(flow)
        if label and not any(lbl.startswith(label) for lbl in labels):
            continue
        if needle:
            hay = " ".join([path.name, flow.get("name", ""), *labels]).lower()
            if needle not in hay:
                continue
        out.append(path)
    return out
