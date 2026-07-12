<div align="center">

<img src="docs/wat-logo.svg" alt="WAT logo" width="120" height="120" />

# WAT — Web Auto Tester

```
        ▲
     ↖  │  ↗
        │
   ◄────●────►      five arrows, inside → outside
        │
     ↙  │  ↘
        ▼
```

**JSON-flow-driven, Playwright-based browser testing for complex, multi-step flows.**

</div>

WAT runs declarative `fl_*.json` "flows" against a real browser (via [Playwright](https://playwright.dev/python/)).
It is a single shared engine that multiple apps consume as a **git submodule** — write a flow once, run
it anywhere, and get attributable diagnostics that tell you whether a failure came from **WAT**, the
**browser**, or the **app itself**.

## Why WAT

- **Complex flows, declaratively.** A broad, documented action/assertion catalog (navigation, interaction,
  browser/session, network mocking, rich assertions) means fewer hand-rolled `eval_js` hacks and brittle sleeps.
- **Playwright under the hood.** Auto-waiting, the trace viewer (`trace.zip`), native console/error capture,
  and multiple browser contexts make long journeys reliable and debuggable.
- **Attributable diagnostics.** Every run writes source-tagged logs (`[WAT]` / `[BROWSER]` / `[APP]`) to a
  temp dir, plus a machine-readable `run.json` that classifies the failure source.
- **Extensible, never forked.** Apps register custom actions/hooks (login, DB seeding, framework-specific
  waits) through a plugin API — the core engine stays generic.

## Quick start

```bash
# 1. Add WAT as a submodule in your app, then initialize it.
git submodule add <WAT-url> tools/WAT
git submodule update --init

# 2. One-shot install (macOS / Linux / Windows). Creates .wat-venv, installs
#    the package + browsers, and self-verifies.
python tools/WAT/install.py --app myapp --extras liveview

# 3. Run a flow (headless by default).
tools/WAT/.wat-venv/bin/wat --flow flows/fl_smoke.json --base-url http://localhost:4000
#   ...or:  python -m wat --flow flows/fl_smoke.json

# 4. Watch it live in a visible browser (headed + slow-mo).
wat --flow flows/fl_smoke.json --live          # or: --headed [--slow-mo 500] [--devtools]
```

Runs are **headless** by default (CI-friendly) and **live/headed** on demand
(`--live` = visible browser + slow-mo; `--headed`, `--slow-mo <ms>`, `--devtools`
give finer control) — the same flow files work in both.

## Documentation

- [`CONTRACT.md`](CONTRACT.md) — the canonical flow schema + action contract (the source of truth).
- [`docs/authoring-flows.md`](docs/authoring-flows.md) — how to write a flow.
- [`docs/action-catalog.md`](docs/action-catalog.md) — the full action/assertion reference.
- [`docs/diagnostics.md`](docs/diagnostics.md) — log layout, source tags, reading a failure.
- [`docs/migrating-from-selenium.md`](docs/migrating-from-selenium.md) — porting existing flows.

## License

MIT.
