# Authoring flows

A flow is a JSON list of steps run against a browser. Start from
[`docs/flow-template.json`](flow-template.json) (copy it to `flows/fl_<name>.json`),
or record a draft from a real session with `wat --record` — see
[`CONTRACT.md`](../CONTRACT.md) for the full schema.

## Recording a draft (`wat --record`)

`wat --record [--flow flows/fl_name.json]` opens a headed browser at `base_url` and
captures what you do — clicks, typing (coalesced to the final value), select/checkbox
changes, Enter/Escape — inferring stable selectors (`data-testid` > `id` > `role`+name >
`name` > short CSS path). Close the browser to write the file.

The output is a **draft**: review the selectors, add the assertions that express what
you meant to verify, and lint with `wat --validate-only --flow <file>`.

## Minimal flow

```json
{
  "name": "Login smoke",
  "label": "auth/smoke",
  "steps": [
    {"action": "open", "url": "/users/log_in"},
    {"action": "type", "by": "testid", "selector": "email", "value": "a@b.com"},
    {"action": "type", "by": "testid", "selector": "password", "value": "secret"},
    {"action": "click", "by": "role", "selector": "button", "name": "Log in"},
    {"action": "assert_url_contains", "value": "/dashboard"}
  ]
}
```

## Guidelines

- **Prefer semantic locators** (`role`, `testid`, `text`, `label`) over brittle CSS/xpath.
- **Avoid `sleep`.** Playwright auto-waits for actionability; use `wait_for`,
  `wait_for_text`, or an `assert_js` Promise when you must synchronize.
- **Capture then interpolate:** `{"action":"capture","selector":"#tok","attr":"value","var":"tok"}`
  then reference `{{tok}}` in later steps.
- **Assertions auto-wait.** Element-state assertions (`assert_visible`, `assert_checked`,
  `assert_enabled`/`disabled`, `assert_value`, `assert_attribute`, `assert_hidden`, the
  text/url/count assertions) poll up to `wait_ms` for the condition to hold, so you rarely
  need an explicit `wait_for` first. Tune with a per-step `timeout` (`timeout: 0` = check
  once). Cumulative checks (`assert_no_console_errors`/`_network_errors`) and negatives
  (`assert_no_element`, `assert_*_not_contains`) are point-in-time by design.
- **Make flaky steps robust declaratively:** add `timeout`, `retry`, `optional`,
  `soft`, or `if`/`skip_if` instead of restructuring the flow.
- **Validate before running:** `wat --validate-only --all` catches unknown actions,
  missing fields, and unresolved variables without launching a browser.

## Accessibility (`assert_a11y`)

Opt in with `extensions = ["a11y"]`. The builtin engine (zero deps) checks the common
WCAG regressions — images without `alt`, buttons/links without accessible names,
unlabeled form controls, missing `<html lang>`, duplicate ids, positive `tabindex`,
focusables inside `aria-hidden`:

```json
{"action": "assert_a11y"}
{"action": "assert_a11y", "selector": "#main", "rules": ["img-alt", "label"], "allow": 1}
```

For full rule coverage, point `a11y_axe_path` (config) or `axe_path` (step) at an
`axe.min.js` your app provides and use `{"engine": "axe", "tags": ["wcag2aa"]}` —
WAT injects it and reports axe's violations in the same shape.

## Visual regression (`assert_screenshot`)

Opt in with `extensions = ["visual"]` (installs the `[visual]` extra for Pillow). The
`assert_screenshot` action captures the page (or a `selector` element) and diffs it against
a committed baseline PNG:

```json
{"action": "assert_screenshot", "name": "dashboard", "max_diff_ratio": 0.01}
```

The first run (or `--update-baselines`) writes the baseline under `visual_baseline_dir`
(default `<root>/baselines`, meant to be committed) and passes; later runs fail if more
than `max_diff_ratio` of pixels differ, writing a `.diff.png` into the run dir. Tune
`max_diff_ratio` / `pixel_threshold` to absorb anti-aliasing noise across machines.

## Reusable fragments (`use`)

Share a login/setup preamble across flows instead of copy-pasting it. Put the fragment
in a subdirectory (so `--all` never runs it standalone) and pull it in with a `use` step:

```json
// flows/fragments/fl_login.json
{"name": "Login fragment", "steps": [
  {"action": "open", "url": "/users/log_in"},
  {"action": "type", "by": "testid", "selector": "email", "value": "a@b.com"},
  {"action": "type", "by": "testid", "selector": "password", "value": "secret"},
  {"action": "click", "by": "role", "selector": "button", "name": "Log in"}
]}
```

```json
// flows/fl_dashboard.json
{"name": "Dashboard", "steps": [
  {"use": "fragments/fl_login.json"},
  {"action": "assert_url_contains", "value": "/dashboard"}
]}
```

The fragment's steps are inlined at load time; captured `{{var}}`s are shared with the
parent. See `CONTRACT.md` for the full rules (path resolution, cycles, nesting).

## Data-driven flows (`matrix`)

Run one journey across many inputs (roles, locales, a table of input->expected) without
copying the flow. Add a `matrix` of rows; each key becomes a `{{var}}` for that run:

```json
{"name": "Headings", "label": "smoke/headings",
 "matrix": [{"path": "/about", "title": "About"}, {"path": "/pricing", "title": "Pricing"}],
 "steps": [
   {"action": "open", "url": "{{path}}"},
   {"action": "assert_title", "value": "{{title}}"}
 ]}
```

Each row runs as its own case (`Headings [path=/about, title=About]`) with a separate run
dir and result, so failures stay attributable per-row. Cases parallelize under
`--all --workers N`.

## Reuse a login across flows (`storage_state`)

Logging in once per flow is slow. Save the authenticated session once, then restore it
everywhere so authenticated flows skip the login form:

```json
// flows/fragments/fl_auth_setup.json  — run once (or first)
{"name": "Auth setup", "steps": [
  {"use": "fragments/fl_login.json"},
  {"action": "save_storage_state", "path": "artifacts/auth/admin.json"}
]}
```

```toml
# wat.toml — every flow restores it (skips login)
storage_state = "artifacts/auth/admin.json"
```

A flow may override with a top-level `"storage_state"` key, or set it to `""` to force a
fresh (logged-out) context. If the file doesn't exist yet, WAT warns and starts fresh
rather than failing. **Never commit a storage-state file** — it holds live session
cookies; keep it under `artifacts/` (gitignored) or another untracked path.

## Custom actions (app plugins)

If your app needs an action WAT doesn't ship, register it in a plugin module and add
it to config `plugins`:

```python
# myapp/wat_plugin.py
from wat import register_action, StepContext

@register_action("open_inbox", required=("user",), group="myapp")
def open_inbox(ctx: StepContext):
    ctx.page.goto(ctx.url(f"/inbox/{ctx.field('user')}"))
```

```toml
# wat.toml
plugins = ["myapp.wat_plugin"]
extensions = ["liveview"]
```
