# Migrating from the old Selenium WAT

The previous WAT was a Selenium `wat.py` copied into each app (Gurim
`tools/WAT/`, Cells `src/utils/WAT/`). This standalone framework is Playwright-based
and consumed as a git submodule. Flows keep living in each app; only their engine and
some field names change.

## 1. Add the submodule and install

```bash
git submodule add <WAT-url> tools/WAT            # or src/utils/WAT for Cells
git submodule update --init
python tools/WAT/install.py --app <name> --extras liveview[,sql]
```

This creates a single `.wat-venv` (delete the old `venv`/`.venv`/`.venv_wat`).

## 2. Move app-specific behavior into a plugin

Anything that was baked into the forked `wat.py` becomes an app plugin registered via
the public API — it never lives in the framework:

| Old (forked into wat.py) | New home |
|--------------------------|----------|
| `login` / `logout` | `wat.ext.auth.PhoenixAuthProvider` + `login_provider(...)` in your plugin |
| `open_messages_*`, `open_class_chat` (Gurim) | `@register_action` in your plugin |
| `sql` / `docker_sql` / `mix_run` (Gurim) | `extensions = ["sql"]` |
| `wait_for_lv` / `phx_push` (Cells) | `extensions = ["liveview"]` |
| cellular-conversation reset (Cells) | a `@reset_hook` in your plugin |

## 3. Field/schema changes

| Old | New canonical |
|-----|---------------|
| `{"value": "..."}` (Gurim) / `{"text": "..."}` (Cells) | `value` (both accepted; `text` is aliased) |
| `by`: `link_text`, `partial_link_text` | use `text` locator |
| bare CSS `selector` | still works (default `by: css`) |
| prefer where possible | `by: role` / `testid` / `text` semantic locators |

## 4. Behavior differences to expect

- **Auto-waiting:** many explicit `sleep`/`wait_for` steps become unnecessary; some
  flows that "passed" only because of sleeps may surface real races — fix those.
- **`assert_js` Promises:** `page.evaluate` awaits a returned Promise, so the old
  `execute_async_script` + `done()` callback pattern must be rewritten to
  `return new Promise(resolve => ...)`. Review these by hand.
- **`real_drag`:** Playwright `drag_to` differs from Selenium ActionChains; verify DnD flows.

## 5. Verify parity

1. Record a pass/fail baseline with the old runner.
2. `wat --validate-only --all` (no browser) to catch schema/plugin gaps.
3. `wat --all` against a running app; diff against the baseline.
4. Open a `trace.zip` for any newly-failing flow to tell a real regression from a
   mistranslation. Only then delete the legacy `wat.py`.
