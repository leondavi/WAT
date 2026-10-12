# WAT — runner contract

The source of truth for the JSON flow schema and the action model. Every
`fl_<name>.json` flow is validated against this contract (`wat --validate-only`).

Run a flow:

```bash
wat --flow flows/fl_smoke.json --base-url http://localhost:4000        # or: python -m wat ...
```

---

## 1. Flow file structure

A flow is one JSON file named `fl_<name>.json` (the `fl_` prefix is enforced).

| Key | Type | Required | Notes |
|-----|------|----------|-------|
| `name` | string | recommended | Human-readable; shown by `--list`. |
| `description` | string | no | Documentation only (never parsed). |
| `label` | string \| [string] | no | Hierarchical tag, e.g. `"sheet/smoke"`. Filter with `--label <prefix>`. |
| `base_url` | string | no | Overrides config `base_url` for this flow. |
| `storage_state` | string | no | Restore this saved storage-state file into the flow's context (empty = force a fresh context). Overrides config `storage_state`. |
| `matrix` | [object] | no | Data-driven rows. The flow runs once per row with each row's keys seeded into the `{{var}}` store. |
| `steps` | [step] | **yes** | Ordered, non-empty list of step objects. |

### `matrix` — data-driven flows

A `matrix` is a list of parameter rows; the flow runs once per row with that row's
keys bound as `{{var}}` values (seeded into the capture store before any step). Each row
is a separate case with its own run dir, artifacts, and result (named `<flow> [k=v]`).

```json
{"name": "Login roles",
 "matrix": [{"role": "admin", "landing": "/admin"}, {"role": "editor", "landing": "/editor"}],
 "steps": [
   {"action": "login", "role": "{{role}}"},
   {"action": "assert_url_contains", "value": "{{landing}}"}
 ]}
```

`--validate-only` treats matrix keys as available variables. Under `--all --workers N`,
matrix cases parallelize across workers like any other flow.

Any other top-level key is ignored.

## 2. Step structure

Every step is `{ "action": "<name>", ...fields, "comment": "<optional>" }`.

**Selector fields** (for actions that target an element):

| Field | Default | Values |
|-------|---------|--------|
| `by` | `css` | `css`, `xpath`, `id`, `name`, `class`, `tag`, `role`, `testid`, `text`, `label`, `placeholder` |
| `selector` | — | The value for `by` (for `role`, this is the ARIA role; add `name` for the accessible name). |
| `has_text` | — | Filter matches to those containing this text. |
| `index` / `nth` | — | Pick the Nth match (0-based). |

**Value field:** the canonical typed/expected value is `value`. `text` is accepted as
an alias and normalized to `value` at load time.

**Per-step robustness keys** (any step):

| Key | Effect |
|-----|--------|
| `timeout` | Per-step timeout in ms (overrides config `wait_ms`). |
| `retry` | Retry the step up to N times with backoff before failing. |
| `optional` | Log and continue if the step fails (never fails the flow). |
| `soft` | Record the failure but keep going; the flow fails at the end with all soft failures. |
| `if` / `skip_if` | A JS expression; run (or skip) the step based on its truthiness. A predicate that throws (or references an unknown `{{var}}`) fails the step as `flow_authoring` rather than silently skipping it. |

`retry`, `optional`, and `soft` apply to every step failure, including Playwright
errors such as a locator timeout, not only to failed assertions.
| `store_as` | Store the step's result/value under this name for `{{...}}` interpolation. |

### `use` — reusable sub-flows

A step of the form `{"use": "<path>"}` (with **no** `action`) inlines another flow's
steps in place, so complex flows can share a login/setup preamble instead of copying it:

```json
{"use": "fragments/fl_login.json"}
```

* The path resolves relative to the **including** flow's directory; the target must be an
  `fl_<name>.json` flow.
* Nesting is allowed; an include cycle is a validation error.
* Expansion happens at load time, so `--validate-only` and a run both see one flat flow.
  Shared state flows through the normal `{{var}}` capture store (capture in the parent,
  reference in the fragment).
* Keep shared fragments in a **subdirectory** of the flows dir (e.g. `flows/fragments/`):
  flow discovery is non-recursive, so fragments are includable by path but never run on
  their own under `--all` / `--list`.
* `use` alongside an `action` in the same object is treated as a normal action step (the
  `use` key is ignored).

## 3. `{{variable}}` interpolation

`capture` (and `store_as`) write into a per-flow store; later steps reference values
with `{{name}}` in any field (except doc fields `comment`/`description`). A reference
to an uncaptured variable is a validation error.

## 4. Actions

See [`docs/action-catalog.md`](docs/action-catalog.md) for the full, generated list
with required fields, or run `wat --print-actions`. Groups: navigation, interaction,
browser/session, network, capture, scripting, assertions, plus opt-in extensions
(liveview, sql, auth, visual, a11y).

### `assert_js` — the workhorse

`script` runs via `page.evaluate` (Promises are awaited natively — no async/sync
split). It must return either:

* a boolean, or
* `{ "pass": true|false, "reason": "...", ...diagnostics }`.

`pass` must be truthy to pass: `null`, `undefined`, `0` and `""` fail (so
`{pass: el && ok}` fails when `el` is missing). An object with no `pass` key passes.

On failure, any extra fields on the returned object (e.g. `why`, `reply`, `label`)
are serialized (JSON, truncated) into the failure reason — they appear in the run
log, `run.json`, and the agent prompt, so you don't need a `console.warn` round-trip
to see them.

```json
{"action": "assert_js",
 "script": "return new Promise(r => setTimeout(() => r({pass: !!window.App, reason: 'App missing'}), 300))"}
```

### Shared JS helpers (config `helpers`)

Set `helpers = "flows/helpers.js"` (config; relative to the app root) to inject one JS
file into **every document of every flow** via Playwright `context.add_init_script`: it
runs before the app's own scripts on the first `open`, on every later navigation or
reload, and on the reset hook's navigation. Flows then call the shared functions from
`assert_js` / `eval_js` without redefining them, and editing the file changes every flow.

* Publish what flows call on `window` (e.g. `window.__watSend = async (text) => {...}`).
  Playwright wraps init scripts in a function, so top-level `function`/`const`
  declarations stay private to the file.
* `wat --validate-only` checks the file once per run: missing/unreadable is an error,
  and when `node` is on PATH a syntax error is too. At run time an unreadable file
  fails the flow up front with source `flow_authoring`.

## 5. Exit codes

| Exit | Meaning |
|------|---------|
| `0` | Flow passed (`wat --all`: every flow passed). |
| `1` | A step failed, or validation found errors, or CLI misuse. |

## 6. Artifacts & diagnostics

Each run writes a per-run directory under `<tmpdir>/wat/<app>/runs/<run_id>/` with
source-tagged logs (`wat.log`, `browser.log`, `app.log`), `steps.jsonl`, `run.json`
(machine-readable result + **failure source**), and, on failure, `trace.zip`,
`<flow>.failed.png/html`, and `<flow>.agent_prompt.txt`. Older run dirs are pruned to
`keep_runs` once, at the start of an invocation; runs from the current invocation are
never pruned, so a large `--all` keeps every artifact its reports point to. See
[`docs/diagnostics.md`](docs/diagnostics.md).

## 7. Extending WAT

Apps register custom actions/hooks in their own plugin module via the public API
(`register_action`, `register_hook`, `login_provider`, `reset_hook`), loaded through
config `plugins`. Hook phases are `before_flow`, `before_step`, `after_step`, and
`after_flow`; `after_flow` runs for passing and failing flows alike (a failing teardown
is logged and never masks the flow result). Core actions never need forking. See
[`docs/authoring-flows.md`](docs/authoring-flows.md) and
[`docs/migrating-from-selenium.md`](docs/migrating-from-selenium.md).

---

_When you add or change an action, update `docs/action-catalog.md` (regenerate) and
this contract in the same commit._
