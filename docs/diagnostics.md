# Diagnostics — is it WAT, the browser, or the app?

Every WAT run writes an attributable trail so you never have to guess which layer
broke. Logs land in a temp dir (ephemeral by design):

```
<tmpdir>/wat/<app>/            # e.g. /tmp/wat/cells/   (override with log_dir / WAT_LOG_DIR)
  latest -> runs/<run_id>      # symlink to the most recent run
  runs/<run_id>/               # run_id = <flow_stem>-<UTC-timestamp>-<pid>
    wat.log        # [WAT]     engine: dispatch, config, driver lifecycle, timings
    browser.log    # [BROWSER] console messages, pageerrors, network failures
    app.log        # [APP]     tailed server-log slices (via tail_log / app_log_path)
    steps.jsonl    #           one JSON record per step (action, status, duration, error)
    run.json       #           machine-readable summary + failure source
    trace.zip      #           Playwright trace (on failure) — open with `playwright show-trace`
    <flow>.failed.png / .failed.html / .agent_prompt.txt
```

## Source tags

Human-readable lines are prefixed by channel so `grep` is unambiguous:

- `[WAT]` — the framework itself (dispatch, driver, config).
- `[BROWSER]` — the page: `console.error`, uncaught `pageerror`, failed/4xx/5xx requests.
- `[APP]` — the app under test, via `tail_log` of its server log.
- `[STEP]` — per-step outcome line.

## Failure classification

On failure, `run.json` sets `source` to one of:

| `source` | Meaning | Where to look |
|----------|---------|---------------|
| `wat_engine` | Bug/timeout inside WAT (driver launch, plugin import). | `wat.log`, the stack. |
| `browser` | The page crashed or emitted errors. | `browser.log`, `trace.zip`. |
| `app` | An assertion about app state failed (the common case). | `browser.log` + app logs + screenshot. |
| `flow_authoring` | Bad selector/field/schema. | Re-run `wat --validate-only`. |

The generated `agent_prompt.txt` leads with this classification, the exact failing
step, and the assertion reason — so a human or a fix-it agent starts at the right layer.

## Quick commands

```bash
wat --doctor                       # environment + where logs will land
cat "$(cat /tmp/wat/<app>/latest.txt 2>/dev/null || echo /tmp/wat/<app>/latest)/run.json"
playwright show-trace /tmp/wat/<app>/latest/trace.zip
```
