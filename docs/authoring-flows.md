# Authoring flows

A flow is a JSON list of steps run against a browser. Start from
[`docs/flow-template.json`](flow-template.json) (copy it to `flows/fl_<name>.json`)
and see [`CONTRACT.md`](../CONTRACT.md) for the full schema.

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
- **Make flaky steps robust declaratively:** add `timeout`, `retry`, `optional`,
  `soft`, or `if`/`skip_if` instead of restructuring the flow.
- **Validate before running:** `wat --validate-only --all` catches unknown actions,
  missing fields, and unresolved variables without launching a browser.

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
